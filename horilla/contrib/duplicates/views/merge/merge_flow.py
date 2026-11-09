"""Merge comparison + summary + final merge."""

# Standard library imports
import json

# Third-party imports (Django)
from django.contrib import messages

# First party imports (Horilla)
from horilla.auth.mixins import LoginRequiredMixin
from horilla.contrib.core.models import HorillaContentType
from horilla.db import transaction
from horilla.shortcuts import get_object_or_404, render
from horilla.urls import reverse
from horilla.utils.decorators import htmx_required, method_decorator
from horilla.utils.translation import gettext
from horilla.utils.translation import gettext_lazy as _
from horilla.views.generic import View
from horilla.web import HttpResponse

_MERGE_SKIP_FIELD_NAMES = frozenset(
    {
        "id",
        "pk",
        "created_at",
        "updated_at",
        "created_by",
        "updated_by",
        "additional_info",
        "company",
    }
)


def iter_model_fields_for_merge(Model):
    """
    Concrete fields shown in merge compare/summary and applied on merge.

    Skips M2M, reverse/auto relations, known audit columns by name, and any
    field with editable=False (auto fields, auto_now timestamps, etc.).
    """

    for field in Model._meta.get_fields():
        if field.name in _MERGE_SKIP_FIELD_NAMES:
            continue
        if getattr(field, "auto_created", False):
            continue
        if hasattr(field, "many_to_many") and field.many_to_many:
            continue
        if not getattr(field, "concrete", True):
            continue
        if not getattr(field, "editable", True):
            continue
        yield field


@method_decorator(htmx_required, name="dispatch")
class MergeDuplicatesCompareView(LoginRequiredMixin, View):
    """
    View to show merge comparison interface.
    """

    def get(self, request, *args, **kwargs):
        """Show merge comparison modal"""

        # Get selected_ids from request
        selected_ids_json = request.GET.get("selected_ids") or request.POST.get(
            "selected_ids"
        )
        if selected_ids_json:
            try:
                duplicate_ids = json.loads(selected_ids_json)
            except json.JSONDecodeError:
                duplicate_ids = request.GET.getlist(
                    "duplicate_ids"
                ) or request.POST.getlist("duplicate_ids")
        else:
            duplicate_ids = request.GET.getlist(
                "duplicate_ids"
            ) or request.POST.getlist("duplicate_ids")

        # Get object_id and content_type_id
        object_id = request.GET.get("object_id") or request.POST.get("object_id")
        content_type_id = request.GET.get("content_type_id") or request.POST.get(
            "content_type_id"
        )

        if not object_id or not content_type_id or not duplicate_ids:
            messages.error(request, _("Missing required parameters."))
            return HttpResponse(_("Missing required parameters."), status=400)

        try:
            # Get the model and main object
            django_content_type = HorillaContentType.objects.get(pk=content_type_id)
            Model = django_content_type.model_class()

            if not Model:
                messages.error(request, gettext("Model not found."))
                return HttpResponse(gettext("Model not found."), status=404)

            main_object = get_object_or_404(Model, pk=object_id)

            # Get selected objects (limit to 3) - these are the records to compare
            # The main_object might be one of the selected records
            selected_objects = Model.objects.filter(pk__in=duplicate_ids[:3])

            if selected_objects.count() == 0:
                messages.error(request, gettext("No duplicates selected."))
                return HttpResponse(gettext("No duplicates selected."), status=400)

            # Get model fields to compare (only user-editable concrete fields)
            fields = []
            for field in iter_model_fields_for_merge(Model):
                # Get field value for each selected record
                field_data = {
                    "name": field.name,
                    "verbose_name": getattr(
                        field, "verbose_name", field.name.replace("_", " ").title()
                    ),
                    "values": {},
                }

                # Selected records values (the 3 selected records - one will become master)
                for idx, selected_obj in enumerate(selected_objects):
                    try:
                        selected_value = getattr(selected_obj, field.name, None)
                        if hasattr(selected_value, "__str__"):
                            field_data["values"][f"record_{idx}"] = (
                                str(selected_value) if selected_value else "[empty]"
                            )
                        else:
                            field_data["values"][f"record_{idx}"] = (
                                selected_value if selected_value else "[empty]"
                            )
                    except Exception:
                        field_data["values"][f"record_{idx}"] = "[empty]"

                fields.append(field_data)

            context = {
                "main_object": main_object,
                "selected_objects": selected_objects,  # The 3 selected duplicates to compare
                "fields": fields,
                "object_id": object_id,
                "content_type_id": content_type_id,
                "duplicate_ids": [str(obj.pk) for obj in selected_objects],
            }

            return render(request, "duplicates/merge_compare.html", context)

        except Exception as e:
            messages.error(
                request,
                gettext("Error loading merge comparison: {error}").format(error=str(e)),
            )
            return HttpResponse(
                gettext("Error: {error}").format(error=str(e)), status=500
            )


class MergeDuplicatesSummaryView(LoginRequiredMixin, View):
    """
    View to show merge summary before final merge.
    """

    def post(self, request, *args, **kwargs):
        """Show merge summary"""

        # Get form data
        object_id = request.POST.get("object_id")
        content_type_id = request.POST.get("content_type_id")
        duplicate_ids = request.POST.getlist("duplicate_ids")

        # Get field selections - all row_user_select* fields
        # Form sends: row_user_select, row_user_select1, row_user_select2, etc.
        field_selections = {}
        for key, value in request.POST.items():
            if key.startswith("row_user_select"):
                # Extract field index: row_user_select -> 0, row_user_select1 -> 1, etc.
                field_index_str = key.replace("row_user_select", "")
                if not field_index_str:
                    field_index_str = "0"
                field_selections[field_index_str] = value

        # Get master record selection
        master_record_selection = request.POST.get("master_record_select", "record_1")

        if not object_id or not content_type_id or not duplicate_ids:
            messages.error(request, gettext("Missing required parameters."))
            return HttpResponse(gettext("Missing required parameters."), status=400)

        try:
            # Get the model and main object
            django_content_type = HorillaContentType.objects.get(pk=content_type_id)
            Model = django_content_type.model_class()

            if not Model:
                messages.error(request, gettext("Model not found."))
                return HttpResponse(gettext("Model not found."), status=404)

            main_object = get_object_or_404(Model, pk=object_id)
            selected_objects = Model.objects.filter(pk__in=duplicate_ids[:3])

            if selected_objects.count() == 0:
                messages.error(request, gettext("No duplicates selected."))
                return HttpResponse(gettext("No duplicates selected."), status=400)

            # Build summary data - map field selections to actual fields
            fields_list = list(iter_model_fields_for_merge(Model))

            summary_data = []
            for idx, field in enumerate(fields_list):
                # Get selection for this field - field names are row_user_select, row_user_select1, row_user_select2, etc.
                field_key = str(idx) if idx > 0 else ""
                # Try to get from field_selections dict first, then from POST directly
                selected_value = field_selections.get(
                    field_key,
                    request.POST.get(
                        f"row_user_select{field_key}", master_record_selection
                    ),
                )

                # Determine which record index was selected
                record_index = 1  # Default to second column
                if selected_value.startswith("record_"):
                    try:
                        record_index = int(selected_value.replace("record_", ""))
                    except ValueError:
                        record_index = 1

                # Get the selected record and its value
                if record_index < selected_objects.count():
                    selected_record = list(selected_objects)[record_index]
                    try:
                        field_value = getattr(selected_record, field.name, None)
                        if hasattr(field_value, "__str__"):
                            field_value = str(field_value) if field_value else "[empty]"
                        else:
                            field_value = field_value if field_value else "[empty]"
                    except Exception:
                        field_value = "[empty]"

                    summary_data.append(
                        {
                            "field_name": getattr(
                                field,
                                "verbose_name",
                                field.name.replace("_", " ").title(),
                            ),
                            "field_value": field_value,
                            "selected_record": selected_record,
                            "field_key": field_key,
                        }
                    )

            # Determine master record
            master_index = 1  # Default to second column
            if master_record_selection.startswith("record_"):
                try:
                    master_index = int(master_record_selection.replace("record_", ""))
                except ValueError:
                    master_index = 1

            master_record = (
                list(selected_objects)[master_index]
                if master_index < selected_objects.count()
                else list(selected_objects)[0]
            )

            context = {
                "main_object": main_object,
                "master_record": master_record,
                "selected_objects": selected_objects,
                "summary_data": summary_data,
                "object_id": object_id,
                "content_type_id": content_type_id,
                "duplicate_ids": duplicate_ids,
                "field_selections": field_selections,
                "master_record_selection": master_record_selection,
            }

            return render(request, "duplicates/merge_summary.html", context)

        except Exception as e:
            messages.error(
                request,
                gettext("Error loading merge summary: {error}").format(error=str(e)),
            )
            return HttpResponse(
                gettext("Error: {error}").format(error=str(e)), status=500
            )


class MergeDuplicatesView(LoginRequiredMixin, View):
    """
    View to handle merging selected duplicates into the main record.
    """

    def post(self, request, *args, **kwargs):
        """Merge selected duplicates into the master record based on selections"""

        # Get form data
        object_id = request.POST.get("object_id")
        content_type_id = request.POST.get("content_type_id")
        duplicate_ids = request.POST.getlist("duplicate_ids")

        field_selections = {}
        for key, value in request.POST.items():
            if key.startswith("row_user_select"):
                field_index_str = key.replace("row_user_select", "")
                if not field_index_str:
                    field_index_str = "0"
                field_selections[field_index_str] = value

        # Get master record selection
        master_record_selection = request.POST.get("master_record_select", "record_1")

        if not object_id or not content_type_id or not duplicate_ids:
            messages.error(request, gettext("Missing required parameters."))
            return self._reload_tab(request, object_id, content_type_id)

        try:
            # Get the model
            django_content_type = HorillaContentType.objects.get(pk=content_type_id)
            Model = django_content_type.model_class()

            if not Model:
                messages.error(request, gettext("Model not found."))
                return self._reload_tab(request, object_id, content_type_id)

            selected_objects = Model.objects.filter(pk__in=duplicate_ids[:3])

            if selected_objects.count() == 0:
                messages.error(request, gettext("No duplicates selected."))
                return self._reload_tab(request, object_id, content_type_id)

            # Determine master record
            master_index = 1  # Default to second column
            if master_record_selection.startswith("record_"):
                try:
                    master_index = int(master_record_selection.replace("record_", ""))
                except ValueError:
                    master_index = 1

            master_record = (
                list(selected_objects)[master_index]
                if master_index < selected_objects.count()
                else list(selected_objects)[0]
            )

            # Get all fields to update - map field selections to actual fields
            fields_list = list(iter_model_fields_for_merge(Model))

            fields_to_update = []
            for idx, field in enumerate(fields_list):
                field_key = str(idx) if idx > 0 else ""
                selected_value = field_selections.get(
                    field_key,
                    request.POST.get(
                        f"row_user_select{field_key}", master_record_selection
                    ),
                )

                record_index = 1  # Default to second column
                if selected_value.startswith("record_"):
                    try:
                        record_index = int(selected_value.replace("record_", ""))
                    except ValueError:
                        record_index = 1

                if record_index < selected_objects.count():
                    source_record = list(selected_objects)[record_index]
                    try:
                        source_value = getattr(source_record, field.name, None)
                        if source_value is not None:
                            fields_to_update.append((field.name, source_value))
                    except Exception:
                        pass

            main_object = get_object_or_404(Model, pk=object_id)

            with transaction.atomic():
                for field_name, field_value in fields_to_update:
                    try:
                        setattr(master_record, field_name, field_value)
                    except Exception:
                        pass

                master_record.save()

                # Delete other duplicate records (not the master)
                other_duplicates = selected_objects.exclude(pk=master_record.pk)
                deleted_count = other_duplicates.delete()[0]

            messages.success(
                request,
                gettext(
                    "Successfully merged {count} duplicate(s) into master record."
                ).format(count=deleted_count),
            )

            # Check if master record is different from detail view object
            if str(master_record.pk) != str(main_object.pk):
                # Get detail URL for master record
                master_detail_url = None
                if hasattr(master_record, "get_detail_url"):
                    try:
                        master_detail_url = master_record.get_detail_url()
                        if hasattr(master_detail_url, "url"):
                            master_detail_url = master_detail_url.url
                    except Exception:
                        pass

                # If no get_detail_url method, try to construct URL
                if not master_detail_url:
                    try:
                        app_label = Model._meta.app_label
                        model_name = Model._meta.model_name
                        # Try common URL patterns
                        try:
                            master_detail_url = reverse(
                                f"{app_label}:{model_name}_detail_view",
                                kwargs={"pk": master_record.pk},
                            )
                        except Exception:
                            try:
                                master_detail_url = reverse(
                                    f"{app_label}:{model_name}_view",
                                    kwargs={"pk": master_record.pk},
                                )
                            except Exception:
                                pass
                    except Exception:
                        pass

                # If we have a URL, return response with SweetAlert and redirect
                if master_detail_url:
                    redirect_script = f"""
                    <script>
                    if (typeof Swal !== 'undefined') {{
                        let timerInterval;
                        let remainingTime = 3000;
                        let isPaused = false;
                        const swalInstance = Swal.fire({{
                            html: '{gettext("The master record is different from the current record. You will be redirected to the master record.")}',
                            icon: "info",
                            showConfirmButton: false,
                            timer: remainingTime,
                            timerProgressBar: true,
                            showClass: {{
                                popup: `animate__animated animate__fadeInUp animate__faster`
                            }},
                            hideClass: {{
                                popup: `animate__animated animate__fadeOutDown animate__faster`
                            }},
                            didOpen: function() {{
                                const popup = Swal.getPopup();
                                if (popup) {{
                                    // Pause timer on mouse enter
                                    popup.addEventListener('mouseenter', function() {{
                                        if (!isPaused) {{
                                            isPaused = true;
                                            Swal.stopTimer();
                                        }}
                                    }});
                                    // Resume timer on mouse leave
                                    popup.addEventListener('mouseleave', function() {{
                                        if (isPaused) {{
                                            isPaused = false;
                                            Swal.resumeTimer();
                                        }}
                                    }});
                                }}
                            }}
                        }}).then(function() {{
                            window.location.href = '{master_detail_url}';
                        }});
                    }} else {{
                        setTimeout(function() {{
                            window.location.href = '{master_detail_url}';
                        }}, 3000);
                    }}
                    </script>
                    """
                    return HttpResponse(redirect_script)

            # Reload the tab to show updated list
            return self._reload_tab(request, object_id, content_type_id)

        except Exception as e:
            messages.error(
                request,
                gettext("Error merging duplicates: {error}").format(error=str(e)),
            )
            return self._reload_tab(request, object_id, content_type_id)

    def _reload_tab(self, request, object_id, content_type_id):
        """Reload the potential duplicates tab"""

        url = reverse("duplicates:potential_duplicates_tab")
        url += f"?object_id={object_id}&content_type_id={content_type_id}"

        return HttpResponse(
            f'<div hx-get="{url}" hx-trigger="load" hx-target="#inner-tab-potential-duplicates-content" hx-swap="innerHTML"></div>'
        )
