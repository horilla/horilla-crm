"""
Settings views for per-company field requiredness.

Lets an admin decide, per company, whether a field on an opted-in model is
required on its create and edit forms, without changing the model definition.
"""

# First party imports (Horilla)
from horilla.auth.mixins import LoginRequiredMixin
from horilla.contrib.core.models import HorillaContentType
from horilla.contrib.generics.views import (
    HorillaListView,
    HorillaNavView,
    HorillaSingleDeleteView,
    HorillaSingleFormView,
    HorillaView,
)
from horilla.urls import reverse_lazy
from horilla.utils.decorators import (
    htmx_required,
    method_decorator,
    permission_required,
    permission_required_or_denied,
)
from horilla.utils.functional import cached_property
from horilla.utils.html import format_html
from horilla.utils.translation import gettext_lazy as _
from horilla.views.generic import View
from horilla.web import HttpResponse, HxTriggerResponse

# Local imports
from ..filters import FieldRequirementFilter
from ..forms import FieldRequirementForm, get_field_choices
from ..models import FieldRequirement


@method_decorator(
    permission_required_or_denied(
        "field_management.view_fieldrequirement",
        wrapper_id="field-requirement-view",
    ),
    name="dispatch",
)
class FieldRequirementView(LoginRequiredMixin, HorillaView):
    """
    Templateview for the field requirements settings page
    """

    template_name = "settings/settings_list_shell.html"
    view_id = "field-requirement-view"
    nav_url = reverse_lazy("field_management:field_requirement_nav_view")
    list_url = reverse_lazy("field_management:field_requirement_list_view")


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required("field_management.view_fieldrequirement"), name="dispatch"
)
class FieldRequirementNavbar(LoginRequiredMixin, HorillaNavView):
    """
    Navbar for the field requirements settings page
    """

    nav_description = _(
        "Choose which fields your team must fill in when creating or editing "
        "records."
    )
    search_url = reverse_lazy("field_management:field_requirement_list_view")
    main_url = reverse_lazy("field_management:field_requirement_view")
    filterset_class = FieldRequirementFilter
    one_view_only = True
    all_view_types = False
    reload_option = False
    model_name = "FieldRequirement"
    model_app_label = "field_management"
    nav_width = False
    url_name = "field_requirement_list_view"

    @cached_property
    def new_button(self):
        """
        Return the configuration for the 'Create Field Requirement' button
        if the user has add permission.
        """
        if self.request.user.has_perm("field_management.add_fieldrequirement"):
            return {
                "url": (
                    f"""{reverse_lazy("field_management:field_requirement_create_form")}?new=true"""
                ),
                "attrs": {"id": "field-requirement-create"},
            }
        return None


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied("field_management.view_fieldrequirement"),
    name="dispatch",
)
class FieldRequirementListView(LoginRequiredMixin, HorillaListView):
    """
    List view of configured field requirements
    """

    model = FieldRequirement
    view_id = "field_requirement_list"
    filterset_class = FieldRequirementFilter
    search_url = reverse_lazy("field_management:field_requirement_list_view")
    main_url = reverse_lazy("field_management:field_requirement_view")
    bulk_update_option = False
    bulk_delete_enabled = False
    bulk_select_option = False
    list_column_visibility = False

    columns = [
        (_("Model"), "model_label"),
        (_("Field"), "field_label"),
        (_("Requirement"), "requirement_label"),
    ]

    _property_column_labels = {
        "model_label": _("Model"),
        "field_label": _("Field"),
        "requirement_label": _("Requirement"),
    }

    def _get_columns(self):
        """Resolve property column headers in the active language."""
        columns = super()._get_columns()
        resolved = []
        for col in columns:
            if isinstance(col, (list, tuple)) and len(col) >= 2:
                label = self._property_column_labels.get(col[1])
                if label is not None:
                    resolved.append([str(label), col[1]])
                    continue
            resolved.append(col)
        return resolved

    @cached_property
    def no_record_add_button(self):
        """
        Get the configuration for the "Add" button when no record exist.
        """
        if self.request.user.has_perm("field_management.add_fieldrequirement"):
            return {
                "url": (
                    f"""{reverse_lazy("field_management:field_requirement_create_form")}?new=true"""
                ),
                "attrs": 'id="field-requirement-create"',
            }
        return None

    actions = [
        {
            "action": "Edit",
            "src": "assets/icons/edit.svg",
            "img_class": "w-4 h-4",
            "permission": "field_management.change_fieldrequirement",
            "attrs": """
                hx-get="{get_edit_url}?new=true"
                hx-target="#modalBox"
                hx-swap="innerHTML"
                onclick="openModal()"
                """,
        },
        {
            "action": "Delete",
            "src": "assets/icons/a4.svg",
            "img_class": "w-4 h-4",
            "permission": "field_management.delete_fieldrequirement",
            "attrs": """
                    hx-post="{get_delete_url}"
                    hx-target="#deleteModeBox"
                    hx-swap="innerHTML"
                    hx-trigger="click"
                    hx-vals='{{"check_dependencies": "true"}}'
                    onclick="openDeleteModeModal()"
                """,
        },
    ]


@method_decorator(htmx_required, name="dispatch")
class FieldRequirementFormView(LoginRequiredMixin, HorillaSingleFormView):
    """
    Create and update form view for a field requirement
    """

    model = FieldRequirement
    form_class = FieldRequirementForm
    fields = ["content_type", "field_name", "is_required"]
    modal_height = False

    @cached_property
    def form_url(self):
        """
        Resolve the form submission URL for create or update operation.
        """
        pk = self.kwargs.get("pk") or self.request.GET.get("id")
        if pk:
            return reverse_lazy(
                "field_management:field_requirement_update_form", kwargs={"pk": pk}
            )
        return reverse_lazy("field_management:field_requirement_create_form")


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied(
        "field_management.delete_fieldrequirement", modal=True
    ),
    name="dispatch",
)
class FieldRequirementDeleteView(LoginRequiredMixin, HorillaSingleDeleteView):
    """
    Delete view for FieldRequirement. Removing a row restores the requiredness
    declared on the model.
    """

    model = FieldRequirement

    def get_post_delete_response(self):
        return HxTriggerResponse()


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required("field_management.view_fieldrequirement"), name="dispatch"
)
class FieldRequirementFieldChoicesView(LoginRequiredMixin, View):
    """
    Return the field options for the model selected in the form.
    """

    def get(self, request, *args, **kwargs):
        """
        Get HTML options for the configurable fields of the selected model.
        """
        content_type_id = request.GET.get("content_type")
        options = format_html('<option value="">{}</option>', _("Select Field"))

        if content_type_id:
            try:
                model = HorillaContentType.objects.get(pk=content_type_id).model_class()
            except (HorillaContentType.DoesNotExist, ValueError, TypeError):
                model = None
            if model is not None:
                for field_name, label in get_field_choices(model):
                    options += format_html(
                        '<option value="{}">{}</option>',
                        field_name,
                        label,
                    )

        return HttpResponse(options)
