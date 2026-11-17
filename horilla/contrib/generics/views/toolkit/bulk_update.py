"""
Bulk update mixin extracted from HorillaListView to keep the main
list view class smaller and focused.
"""

# Standard library imports
import json
import logging
from decimal import Decimal
from functools import reduce
from operator import or_

# Third-party imports
from auditlog.models import LogEntry

# Third-party imports (Django)
from django.contrib import messages

from horilla.contrib.core.models import HorillaContentType
from horilla.contrib.core.utils import get_editable_fields
from horilla.db.models import Q
from horilla.shortcuts import render
from horilla.urls import reverse_lazy

# First party imports (Horilla)
from horilla.utils import timezone
from horilla.utils.translation import gettext_lazy as _
from horilla.web import HttpResponse, ScriptResponse

logger = logging.getLogger(__name__)


class HorillaBulkUpdateMixin:
    """
    Mixin that encapsulates all bulk update logic so that HorillaListView
    can delegate to it instead of implementing everything inline.
    """

    def apply_bulk_update_choices(self, field_infos):
        """
        Replace the options of fields listed in ``bulk_update_choices`` with the
        view's own limited set, and link the country/state pairs listed in
        ``bulk_update_country_state_fields`` so the states reload when the country
        changes. Returns new dicts; the input is not modified.
        """
        overrides = getattr(self, "bulk_update_choices", None) or {}
        pairs = getattr(self, "bulk_update_country_state_fields", None) or {}
        parents = {child: parent for parent, child in pairs.items()}
        options_url = str(reverse_lazy("core:get_country_subdivisions"))
        result = []
        for info in field_infos:
            name = info["name"]
            get_choices = overrides.get(name)
            if get_choices:
                info = {
                    **info,
                    "choices": [
                        {"value": value, "label": label}
                        for value, label in get_choices()
                    ],
                }
            if name in parents:
                info = {**info, "depends_on": parents[name]}
            if name in pairs:
                info = {
                    **info,
                    "dependent": {"child": pairs[name], "url": options_url},
                }
            result.append(info)
        return result

    def handle_bulk_update_post(self, request, record_ids, columns):
        """
        Entry point from HorillaListView.post for bulk update paths.

        Returns an HttpResponse if a bulk update should be processed here,
        otherwise None (so the caller can continue its own logic).
        """
        if request.POST.get("bulk_update_form") == "true":
            return HorillaBulkUpdateMixin._handle_bulk_update_form_render(self, request)

        result = HorillaBulkUpdateMixin._handle_bulk_update_values(
            self, request, record_ids
        )
        if result is not None:
            return result

        if request.POST.get("bulk_update_field"):
            return HorillaBulkUpdateMixin._handle_legacy_bulk_update(
                self, request, record_ids
            )

        return None

    def _handle_bulk_update_form_render(self, request):
        """Render the bulk update modal for the selected rows."""
        selected_ids = request.POST.get("selected_ids", "[]")
        try:
            selected_ids = json.loads(selected_ids)
            selected_ids = [int(id) for id in selected_ids if str(id).isdigit()]
            valid_ids = (
                self.get_queryset()
                .filter(id__in=selected_ids)
                .values_list("id", flat=True)
            )
            valid_ids = list(valid_ids)

            self.object_list = self.get_queryset()
            context = self.get_context_data()
            context["selected_ids"] = selected_ids
            context["selected_ids_json"] = json.dumps(selected_ids)
            return HorillaBulkUpdateMixin.render_bulk_update_form(
                self, request, context
            )
        except (json.JSONDecodeError, ValueError) as e:
            logger.error("Error processing selected_ids: %s", str(e))
            self.object_list = self.get_queryset()
            context = self.get_context_data()
            context["selected_ids"] = []
            context["selected_ids_json"] = json.dumps([])
            return HorillaBulkUpdateMixin.render_bulk_update_form(
                self, request, context
            )

    def _handle_bulk_update_values(self, request, record_ids):
        """
        Apply a bulk update when `record_ids` is present and at least one
        `bulk_update_value_<field>` was posted; otherwise return None so the
        caller can fall through to other handlers (e.g. legacy/export).
        """
        if not record_ids:
            return None

        try:
            record_ids_list = json.loads(record_ids)
        except json.JSONDecodeError:
            return HttpResponse("Invalid JSON data for record_ids", status=400)

        editable_bulk_field_names = get_editable_fields(
            request.user, self.model, self.bulk_update_fields
        )
        bulk_updates = {}
        for field in editable_bulk_field_names:
            value = request.POST.get(f"bulk_update_value_{field}")
            if value:
                bulk_updates[field] = value

        if not bulk_updates:
            return None

        return HorillaBulkUpdateMixin.handle_bulk_update(
            self, record_ids_list, bulk_updates
        )

    def _handle_legacy_bulk_update(self, request, record_ids):
        """Handle the legacy single field/value bulk update form."""
        field_name = request.POST.get("bulk_update_field")
        new_value = request.POST.get("bulk_update_value")
        if record_ids and field_name and new_value:
            try:
                record_ids_list = json.loads(record_ids)
            except json.JSONDecodeError:
                return HttpResponse("Invalid JSON data for record_ids", status=400)
            return HorillaBulkUpdateMixin.handle_bulk_update(
                self, record_ids_list, {field_name: new_value}
            )
        return HttpResponse("Invalid request: Missing required fields", status=400)

    def render_bulk_update_form(self, request, context):
        """Render the bulk update modal."""

        return render(request, "partials/bulk_update_form.html", context)

    def parse_bulk_date_value(self, value, user=None):
        """Parse a bulk-update date string via composed DateTimeFormatter."""
        from horilla.extension.formatting.resolve import get_datetime_formatter

        parsed = get_datetime_formatter().parse_date(value, user=user)
        if parsed is None:
            raise ValueError(f"Invalid date value: {value}")
        return parsed

    def parse_bulk_datetime_value(self, value, user=None):
        """Parse a bulk-update datetime string via composed DateTimeFormatter."""
        from horilla.extension.formatting.resolve import get_datetime_formatter

        parsed = get_datetime_formatter().parse_datetime(value, user=user)
        if parsed is None:
            raise ValueError(f"Invalid datetime value: {value}")
        return parsed

    def handle_bulk_update(self, record_ids, bulk_updates):
        """
        Perform and validate bulk updates for given record IDs.

        Coerces values according to field types and applies the updates; returns
        an HTTP response with error info on failure. Only fields with read+write
        permission are applied.
        """
        try:
            queryset, skipped_count, denied_response = (
                HorillaBulkUpdateMixin._resolve_bulk_update_queryset(self, record_ids)
            )
            if denied_response is not None:
                return denied_response

            update_dict, coercion_error = HorillaBulkUpdateMixin._coerce_bulk_updates(
                self, bulk_updates
            )
            if coercion_error is not None:
                return coercion_error

            if not update_dict:
                messages.info(
                    self.request, "No fields were updated as no values were provided."
                )
                return ScriptResponse(
                    reload=True,
                    extra=f"$('#unselect-all-btn-{self.view_id}').click();",
                )

            updated_count = HorillaBulkUpdateMixin._apply_bulk_update(
                self, queryset, record_ids, update_dict
            )
            HorillaBulkUpdateMixin._notify_bulk_update_result(
                self, updated_count, skipped_count
            )

            self.object_list = self.get_queryset()
            return ScriptResponse(
                reload=True,
                extra=f"$('#unselect-all-btn-{self.view_id}').click();",
            )

        except Exception as e:
            return HttpResponse(f"Bulk update failed: {str(e)}", status=500)

    def _resolve_bulk_update_queryset(self, record_ids):
        """
        Return ``(queryset, skipped_count, denied_response)`` for the bulk
        update, restricting to owned records when the user only has
        ``change_own`` permission.

        ``denied_response`` is an ``HttpResponse`` when the user has neither
        permission, otherwise ``None``.
        """
        user = self.request.user
        app_label = self.model._meta.app_label
        model_name = self.model._meta.model_name
        change_perm = f"{app_label}.change_{model_name}"
        change_own_perm = f"{app_label}.change_own_{model_name}"

        has_change = user.has_perm(change_perm)
        has_change_own = user.has_perm(change_own_perm)

        if not has_change and not has_change_own:
            messages.error(
                self.request, "You do not have permission to update this data."
            )
            return None, 0, ScriptResponse(reload=True)

        queryset = self.get_queryset().filter(id__in=record_ids)

        # If user lacks global change permission but has change_own,
        # restrict the update queryset to only records they own.
        if not has_change and has_change_own:
            owner_fields = getattr(self.model, "OWNER_FIELDS", None)
            ownership_query = None
            if owner_fields:
                ownership_query = reduce(
                    or_,
                    (Q(**{field: user}) for field in owner_fields),
                    Q(),
                )

            from ..helpers.queryset_utils import get_granted_access_filter

            granted_query = get_granted_access_filter(self.model, user, "change")
            if granted_query is not None:
                ownership_query = (
                    granted_query
                    if ownership_query is None
                    else ownership_query | granted_query
                )

            if ownership_query is not None:
                queryset = queryset.filter(ownership_query).distinct()
            else:
                queryset = queryset.none()

        skipped_count = len(record_ids) - queryset.count()
        return queryset, skipped_count, None

    def _coerce_bulk_updates(self, bulk_updates):
        """
        Coerce each posted ``bulk_updates`` value according to its field
        type.

        Returns ``(update_dict, error_response)``; ``error_response`` is an
        ``HttpResponse`` when a field is unknown or a value is invalid,
        otherwise ``None``.
        """
        # Use list view's field metadata when available (avoids cyclic import)
        if hasattr(self, "_get_model_fields"):
            field_infos = {
                field["name"]: field
                for field in HorillaBulkUpdateMixin.apply_bulk_update_choices(
                    self, self._get_model_fields()
                )
            }
        else:
            field_infos = {}

        editable_bulk_field_names = get_editable_fields(
            self.request.user, self.model, self.bulk_update_fields
        )
        editable_bulk_set = set(editable_bulk_field_names)

        update_dict = {}
        for field_name, new_value in bulk_updates.items():
            if field_name not in editable_bulk_set:
                continue
            if new_value == "" or new_value is None:
                continue

            field_info = field_infos.get(field_name)
            if not field_info:
                return None, HttpResponse(f"Field {field_name} not found", status=400)

            coerced, error_response = HorillaBulkUpdateMixin._coerce_bulk_update_value(
                self, field_name, new_value, field_info
            )
            if error_response is not None:
                return None, error_response
            update_dict[field_name] = coerced

        return update_dict, None

    def _coerce_bulk_update_value(self, field_name, new_value, field_info):
        """Coerce a single bulk-update value per ``field_info["type"]``."""
        field_type = field_info["type"]
        try:
            if field_type == "boolean":
                new_value = str(new_value).lower() in ("true", "yes", "1")
            elif field_type in ("number", "integer"):
                new_value = int(new_value)
            elif field_type in ("float", "decimal"):
                new_value = Decimal(new_value)
            elif field_type == "date":
                new_value = HorillaBulkUpdateMixin.parse_bulk_date_value(
                    self, new_value, user=self.request.user
                )
            elif field_type == "datetime":
                new_value = HorillaBulkUpdateMixin.parse_bulk_datetime_value(
                    self, new_value, user=self.request.user
                )
            elif field_type == "choice":
                choices = [c["value"] for c in field_info.get("choices", [])]
                if new_value not in choices:
                    return None, HttpResponse(
                        f"Invalid choice for {field_name}", status=400
                    )
            elif field_type == "foreignkey":
                if new_value == "":
                    new_value = None
                elif new_value:
                    try:
                        new_value = int(new_value)
                    except ValueError:
                        pass
            return new_value, None
        except ValueError as e:
            return None, HttpResponse(
                f"Invalid value for field {field_name}: {str(e)}", status=400
            )

    def _apply_bulk_update(self, queryset, record_ids, update_dict):
        """Apply ``update_dict`` to ``queryset`` and audit-log the changes."""
        records_before = {obj.id: obj for obj in queryset}
        content_type = HorillaContentType.objects.get_for_model(self.model)
        user = self.request.user if self.request.user.is_authenticated else None

        updated_count = queryset.update(**update_dict)

        if updated_count > 0:
            for record_id in record_ids:
                if record_id not in records_before:
                    continue
                record = records_before[record_id]
                updated_record = self.model.objects.get(id=record_id)

                changes = {}
                for field_name in update_dict:
                    old_value = getattr(record, field_name, None)
                    new_value = getattr(updated_record, field_name, None)
                    if old_value != new_value:
                        changes[field_name] = [
                            str(old_value) if old_value is not None else "--",
                            str(new_value) if new_value is not None else "--",
                        ]

                if changes:
                    LogEntry.objects.create(
                        content_type=content_type,
                        object_id=record_id,
                        object_repr=str(updated_record),
                        action=LogEntry.Action.UPDATE,
                        actor=user,
                        timestamp=timezone.now(),
                        changes=changes,
                    )

        return updated_count

    def _notify_bulk_update_result(self, updated_count, skipped_count):
        """Flash the success/warning message summarizing the bulk update."""
        if skipped_count > 0:
            messages.warning(
                self.request,
                _(
                    "Updated %(updated)d record(s) successfully. "
                    "%(skipped)d record(s) were skipped because you do not "
                    "have permission to update them."
                )
                % {"updated": updated_count, "skipped": skipped_count},
            )
        else:
            messages.success(
                self.request,
                _("Updated %(count)d records successfully.") % {"count": updated_count},
            )
