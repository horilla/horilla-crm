"""
This view handles the methods for recycle bin view
"""

# Standard library imports
import json
from functools import cached_property

# Third-party imports (Django)
from django.contrib import messages

# First party imports (Horilla)
from horilla.auth.mixins import LoginRequiredMixin
from horilla.contrib.generics.views import HorillaListView, HorillaNavView, HorillaView
from horilla.shortcuts import get_object_or_404, render
from horilla.urls import reverse_lazy
from horilla.utils.decorators import (
    htmx_required,
    method_decorator,
    permission_required,
    permission_required_or_denied,
)
from horilla.utils.html import escapejs
from horilla.utils.translation import gettext_lazy as _
from horilla.views.generic import View
from horilla.web import HttpResponse, HxTriggerResponse, RefreshResponse, ScriptResponse

# Local imports
from ..models import RecycleBin, RecycleBinPolicy
from ..utils import delete_recycle_bin_records, restore_recycle_bin_records


@method_decorator(
    permission_required_or_denied(
        "core.view_recyclebin", wrapper_id="recycle-bin-view"
    ),
    name="dispatch",
)
class RecycleBinView(LoginRequiredMixin, HorillaView):
    """
    TemplateView for recycle bin page.
    """

    template_name = "settings/settings_list_shell.html"
    view_id = "recycle-bin-view"
    nav_url = reverse_lazy("core:recycle_bin_navbar")
    list_url = reverse_lazy("core:recycle_bin_list_view")


@method_decorator(htmx_required, name="dispatch")
@method_decorator(permission_required("core.view_recyclebin"), name="dispatch")
class RecycleBinNavbar(LoginRequiredMixin, HorillaNavView):
    """
    navbar for recyclebin
    """

    nav_description = _("Restore or permanently delete removed records.")
    main_url = reverse_lazy("core:recycle_bin_view")
    one_view_only = True
    all_view_types = False
    filter_option = False
    reload_option = False
    model_name = "RecycleBin"
    model_app_label = "core"
    nav_width = False
    url_name = "recycle_bin_list_view"
    search_option = False
    border_enabled = False


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied("core.view_recyclebin"), name="dispatch"
)
class RecycleBinListView(LoginRequiredMixin, HorillaListView):
    """
    listview for recyclebin
    """

    model = RecycleBin
    view_id = "RecycleBinlist"
    main_url = reverse_lazy("core:recycle_bin_view")
    bulk_update_option = False
    bulk_delete_enabled = False
    bulk_export_option = False
    list_column_visibility = False

    @cached_property
    def custom_bulk_actions(self):
        """
        Return bulk restore and delete action configurations for the recycle bin.
        """
        restore_msg = escapejs(
            _("Are you sure you want to restore the selected items?")
        )
        delete_msg = escapejs(_("Are you sure you want to delete the selected items?"))
        delete_hint = escapejs(
            _(
                "When deleting the items, its dependent data will be set to NULL or reassigned."
            )
        )
        return [
            {
                "name": "restore",
                "label": "Restore",
                "url": reverse_lazy("core:bulk_recycle_bin_restore"),
                "method": "post",
                "icon": "fa-undo",
                "bg_color": "#e8f5e9",
                "hover_bg_color": "#4caf50",
                "text_color": "#2e7d32",
                "border_color": "#a5d6a7",
                "hover_text_color": "white",
                "target": "#deleteModeBox",
                "swap": "innerHTML",
                "trigger": "confirmed",
                "hx_click": f"hxConfirm(this,'{restore_msg}')",
            },
            {
                "name": "delete",
                "label": "Delete",
                "url": reverse_lazy("core:bulk_recycle_bin_delete"),
                "method": "post",
                "target": "#modalBox",
                "swap": "innerHTML",
                "icon": "fa-trash-alt",
                "bg_color": "#c0392b26",
                "hover_bg_color": "#c0392b",
                "text_color": "#c0392b",
                "border_color": "#c0392b42",
                "hover_text_color": "white",
                "target": "#deleteModeBox",
                "swap": "innerHTML",
                "trigger": "confirmed",
                "hx_click": f"hxConfirm(this,'{delete_msg}','{delete_hint}')",
            },
        ]

    @cached_property
    def additional_action_button(self):
        """
        Return the empty recycle bin action button configuration.
        """
        empty_msg = escapejs(_("Are you sure you want to empty this bin?"))
        return [
            {
                "name": "empty_recyclebin",
                "label": "Empty Recycle Bin",
                "url": reverse_lazy("core:recycle_bin_empty"),
                "method": "post",
                "icon": "fa-recycle",
                "bg_color": "#f44336",
                "text_color": "white",
                "border_color": "#ef9a9a",
                "target": "#deleteModeBox",
                "swap": "innerHTML",
                "trigger": "confirmed",
                "hx_click": f"hxConfirm(this,'{empty_msg}')",
            },
        ]

    @cached_property
    def columns(self):
        """
        Returns the list of columns to display in the recycle bin list view.
        """
        _instance = self.model()
        return [
            (_("Record Name"), "record_name"),
            (_("Type"), "get_model_display_name"),
            "deleted_by",
            "deleted_at",
        ]

    @cached_property
    def actions(self):
        """
        Return per-row restore and delete action configurations.
        """
        restore_msg = escapejs(_("Are you sure you want to restore this item?"))
        delete_msg = escapejs(_("Are you sure you want to delete this item?"))
        delete_hint = escapejs(
            _(
                "When deleting the item, its dependent data will be set to NULL or reassigned."
            )
        )
        return [
            {
                "action": "Restore",
                "icon": "fa-solid fa-undo",
                "icon_class": "fa-solid fa-undo w-4 h-4",
                "permission": "core.change_recyclebin",
                "attrs": f"""
                    hx-post="{{get_restore_url}}"
                    hx-target="#modalBox"
                    hx-swap="innerHTML"
                    hx-trigger='confirmed'
                    hx-on:click="hxConfirm(this,'{restore_msg}')"
                    """,
            },
            {
                "action": "Delete",
                "src": "assets/icons/a4.svg",
                "img_class": "w-4 h-4",
                "permission": "core.delete_recyclebin",
                "attrs": f"""
                hx-post="{{get_delete_url}}"
                hx-target="#deleteModeBox"
                hx-swap="innerHTML"
                hx-trigger='confirmed'
                hx-on:click="hxConfirm(this,'{delete_msg}','{delete_hint}')"
            """,
            },
        ]


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied("core.delete_recyclebin"), name="dispatch"
)
class RecycleDeleteView(LoginRequiredMixin, View):
    """
    View to handle deletion of a single RecycleBin record
    """

    def post(self, request, pk, *args, **kwargs):
        """
        Handle POST request to delete a RecycleBin record.
        """

        try:
            recycle_obj = get_object_or_404(RecycleBin, pk=pk)
        except Exception:
            messages.error(request, _("The requested data does not exist."))
            return ScriptResponse(reload=True)
        deleted_count, failed_records = delete_recycle_bin_records(request, recycle_obj)

        if deleted_count > 0:
            messages.success(
                request, f"Record '{recycle_obj.record_name()}' deleted successfully."
            )
        if failed_records:
            messages.error(request, f"Error deleting record: {failed_records[0]}")

        return HxTriggerResponse(status=200)


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied("core.delete_recyclebin"), name="dispatch"
)
class BulkDeleteRecycleBinView(LoginRequiredMixin, View):
    """
    View to handle bulk deletion of selected RecycleBin records
    """

    def post(self, request, *args, **kwargs):
        """
        Handle POST request to bulk delete RecycleBin records.
        """
        record_ids = json.loads(request.POST.get("selected_ids", "[]"))
        if not record_ids:
            messages.error(request, _("No records selected for deletion."))
            response = HttpResponse(status=204)
            response["HX-Redirect"] = reverse_lazy("core:recycle_bin_view")
            return response
        recycle_objs = RecycleBin.objects.filter(id__in=record_ids)
        deleted_count, failed_records = delete_recycle_bin_records(
            request, recycle_objs
        )
        if deleted_count > 0:
            messages.success(
                request,
                f"Successfully deleted {deleted_count} item(s) from the recycle bin.",
            )
        if failed_records:
            messages.warning(
                request,
                f"Failed to delete {len(failed_records)} item(s): {', '.join(failed_records)}",
            )
        return HxTriggerResponse(
            extra="$('#unselect-all-btn-RecycleBinlist').click();closeModal();"
        )


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied("core.change_recyclebin"), name="dispatch"
)
class RecycleRestoreView(LoginRequiredMixin, View):
    """
    View to handle restoration of a single RecycleBin record
    """

    def post(self, request, pk, *args, **kwargs):
        """
        Handle POST request to restore a RecycleBin record.
        """
        try:
            recycle_obj = get_object_or_404(RecycleBin, pk=pk)
        except Exception:
            messages.error(request, _("The requested data does not exist."))
            return ScriptResponse(reload=True)
        restored_count, failed_records = restore_recycle_bin_records(
            request, recycle_obj
        )

        if restored_count > 0:
            messages.success(
                request, f"Record '{recycle_obj.record_name()}' restored successfully."
            )
        if failed_records:
            messages.error(request, f"Error restoring record: {failed_records[0]}")

        return HxTriggerResponse(status=200)


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied("core.change_recyclebin"), name="dispatch"
)
class BulkRestoreRecycleView(LoginRequiredMixin, View):
    """
    View to handle bulk restoration of selected RecycleBin records
    """

    def post(self, request, *args, **kwargs):
        """
        Handle POST request to bulk restore RecycleBin records.
        """
        record_ids = json.loads(request.POST.get("selected_ids", "[]"))
        if not record_ids:
            messages.error(request, _("No records selected for restoration."))
            response = HttpResponse(status=204)
            response["HX-Redirect"] = reverse_lazy("core:recycle_bin_view")
            return response
        recycle_objs = RecycleBin.objects.filter(id__in=record_ids)
        restored_count, failed_records = restore_recycle_bin_records(
            request, recycle_objs
        )
        if restored_count > 0:
            messages.success(
                request,
                f"Successfully restored {restored_count} item(s) from the recycle bin.",
            )
        if failed_records:
            messages.warning(
                request,
                f"Failed to restore {len(failed_records)} item(s).",
            )
        return ScriptResponse(
            reload=True,
            extra="$('#unselect-all-btn-RecycleBinlist').click();",
            close=True,
            status=200,
        )


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied("core.delete_recyclebin"), name="dispatch"
)
class EmptyRecycleBinView(LoginRequiredMixin, View):
    """
    View to handle emptying the entire RecycleBin model
    """

    def post(self, request, *args, **kwargs):
        """
        Handle POST request to empty the recycle bin.
        """
        deleted_count, _ = RecycleBin.objects.all().delete()

        messages.success(
            request,
            f"Successfully deleted {deleted_count} item(s) from the recycle bin.",
        )

        response = HttpResponse(status=204)
        response["HX-Redirect"] = reverse_lazy("core:recycle_bin_view")
        return response


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied("core.view_recyclebinpolicy"), name="dispatch"
)
class BinPolicyView(LoginRequiredMixin, View):
    """
    TemplateView for recycle bin policy view.
    """

    template_name = "settings/recycle_bin/bin_policy.html"

    def get(self, request, *args, **kwargs):
        """
        Handle GET request to display the recycle bin policy.
        """
        company = request.active_company
        policy = RecycleBinPolicy.objects.filter(company=company).first()
        context = {
            # 0 retention days means no expiry; show the default days in the field
            "days": (policy.retention_days if policy else 0) or 30,
            "no_expiry": bool(policy and policy.retention_days == 0),
        }
        return render(request, self.template_name, context)

    def post(self, request, *args, **kwargs):
        """
        Handle POST request to update the recycle bin policy.
        """
        if not request.user.has_perm("core.change_recyclebinpolicy"):
            messages.error(request, _("You don't have permission to do this change"))
            return render(request, "403.html")

        company = request.active_company

        if request.POST.get("no_expiry") == "on":
            # 0 retention days means records are never deleted automatically
            days = 0
        else:
            # Turning No expiry off sends no days (the field was disabled): use the default
            raw_days = request.POST.get("days", "30")
            try:
                days = int(raw_days)
                if days < 1:
                    raise ValueError
            except (TypeError, ValueError):
                messages.error(request, _("Enter a valid retention period in days."))
                return RefreshResponse(request)

        policy, created = RecycleBinPolicy.objects.get_or_create(
            company=company, defaults={"retention_days": days}
        )

        if not created:
            policy.retention_days = days
            policy.save()
        messages.success(request, _("Recycle bin policy updated successfully."))
        return HttpResponse("")
