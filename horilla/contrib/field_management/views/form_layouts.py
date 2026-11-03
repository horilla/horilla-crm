"""
Settings views for per-company form layouts.

Lets an admin choose, per company, which fields of an opted-in model appear
and in what order, without changing the model or its default forms — the
layout is offered as an opt-in "Custom Layout" form mode on both create and
edit requests (see ``horilla/contrib/field_management/extensions/form_layouts.py``).

The menu opens a list of saved layouts (like Custom Fields). "New" asks only
for the model, stores a layout with every field shown, and opens that
layout's detail page, where admins with change permission switch it into edit
mode, change visibility and order, and save or cancel back to the detail view.
"""

# Third-party imports (Django)
from django.contrib import messages

from horilla.auth.mixins import LoginRequiredMixin

# First party imports (Horilla)
from horilla.contrib.core.models import HorillaContentType
from horilla.contrib.generics.views import (
    HorillaListView,
    HorillaNavView,
    HorillaSingleFormView,
    HorillaView,
)
from horilla.shortcuts import render
from horilla.urls import reverse, reverse_lazy
from horilla.utils.decorators import (
    htmx_required,
    method_decorator,
    permission_required,
    permission_required_or_denied,
)
from horilla.utils.functional import cached_property
from horilla.utils.translation import gettext_lazy as _
from horilla.views.generic import View
from horilla.web import Http404, HttpResponse, ScriptResponse

# Local imports
from ..filters import FormLayoutFilter
from ..forms import FormLayoutCreateForm
from ..models import FormLayoutField
from ..registry.form_layouts import get_configurable_models
from ..utils.form_layouts import (
    build_layout_entries,
    get_form_layout,
    reset_form_layout,
    save_form_layout,
)

MODE_VIEW = "view"
MODE_EDIT = "edit"

VIEW_PERM = "field_management.view_formlayoutfield"
ADD_PERM = "field_management.add_formlayoutfield"
CHANGE_PERM = "field_management.change_formlayoutfield"
DELETE_PERM = "field_management.delete_formlayoutfield"

CREATE_URL = reverse_lazy("field_management:form_layout_create")


@method_decorator(
    permission_required_or_denied(VIEW_PERM, wrapper_id="form-layout-view"),
    name="dispatch",
)
class FormLayoutListPageView(LoginRequiredMixin, HorillaView):
    """Shell view for the form layouts settings page."""

    template_name = "settings/settings_list_shell.html"
    view_id = "form-layout-view"
    nav_url = reverse_lazy("field_management:form_layout_navbar")
    list_url = reverse_lazy("field_management:form_layout_list")


@method_decorator(htmx_required, name="dispatch")
@method_decorator(permission_required(VIEW_PERM), name="dispatch")
class FormLayoutNavbar(LoginRequiredMixin, HorillaNavView):
    """Navbar for the form layouts settings page."""

    nav_title = _("Form Layout")
    nav_description = _(
        "Choose which fields appear and in what order. "
        "Available as a Custom Layout mode on create and edit forms."
    )
    search_url = reverse_lazy("field_management:form_layout_list")
    main_url = reverse_lazy("field_management:form_layout_view")
    filterset_class = FormLayoutFilter
    one_view_only = True
    all_view_types = False
    reload_option = False
    model_name = "FormLayoutField"
    model_app_label = "field_management"
    nav_width = False
    url_name = "form_layout_list"

    @cached_property
    def new_button(self):
        """Create-button config when the user may add layouts."""
        if self.request.user.has_perm(ADD_PERM):
            return {
                "url": f"{CREATE_URL}?new=true",
                "attrs": {"id": "form-layout-create"},
            }
        return None


@method_decorator(htmx_required, name="dispatch")
@method_decorator(permission_required_or_denied(VIEW_PERM), name="dispatch")
class FormLayoutListView(LoginRequiredMixin, HorillaListView):
    """One row per model that has a saved layout."""

    model = FormLayoutField
    view_id = "form_layout_list"
    filterset_class = FormLayoutFilter
    search_url = reverse_lazy("field_management:form_layout_list")
    main_url = reverse_lazy("field_management:form_layout_view")
    bulk_update_option = False
    bulk_delete_enabled = False
    bulk_select_option = False
    list_column_visibility = False
    columns = [
        (_("Model"), "model_label"),
        (_("Fields Shown"), "fields_shown"),
        (_("Last Updated"), "updated_at"),
    ]
    col_attrs = [
        {
            "model_label": {
                "hx-get": "{get_detail_url}",
                "hx-target": "#settings-content",
                "hx-select": "#form-layout-view",
                "hx-swap": "innerHTML",
                "hx-push-url": "true",
                "style": "cursor:pointer",
            }
        }
    ]
    actions = [
        {
            "action": _("Delete"),
            "src": "assets/icons/a4.svg",
            "img_class": "w-4 h-4",
            "permission": DELETE_PERM,
            "attrs": """
                hx-post="{get_delete_url}"
                hx-trigger="confirmed"
                hx-swap="none"
                onclick="hxConfirm(this, 'Delete this form layout? The create form goes back to the default.')"
            """,
        },
    ]

    def get_queryset(self):
        """A layout stores one row per field; sequence 1 is one row per model."""
        queryset = super().get_queryset()
        return queryset.filter(sequence=1)

    @cached_property
    def no_record_add_button(self):
        """Empty-state add button when the user may add layouts."""
        if self.request.user.has_perm(ADD_PERM):
            return {
                "url": f"{CREATE_URL}?new=true",
                "attrs": 'id="form-layout-create"',
            }
        return None


def detail_url(content_type_id):
    """Return the detail page URL for a model's layout."""
    return reverse(
        "field_management:form_layout_detail", kwargs={"ct": content_type_id}
    )


@method_decorator(htmx_required, name="dispatch")
@method_decorator(permission_required_or_denied(ADD_PERM, modal=True), name="dispatch")
class FormLayoutCreateView(LoginRequiredMixin, HorillaSingleFormView):
    """Modal form: pick a model, store its default layout, open the detail page."""

    model = FormLayoutField
    form_class = FormLayoutCreateForm
    fields = ["content_type"]
    modal_height = False
    form_title = _("Create Form Layout")
    save_and_new = False
    form_url = CREATE_URL
    full_width_fields = ["content_type"]

    def form_valid(self, form):
        """Store the layout with every field shown, then open its detail page."""
        content_type = form.cleaned_data["content_type"]
        model = content_type.model_class()
        if model is None:
            form.add_error("content_type", _("Select a valid model."))
            return self.form_invalid(form)
        save_form_layout(
            model,
            ordered_names=[],
            visible_names=[
                entry.name for entry in build_layout_entries(model, self.request)
            ],
            company=getattr(self.request, "active_company", None),
            request=self.request,
        )
        messages.success(self.request, _("Form layout created."))
        url = detail_url(content_type.pk)
        return ScriptResponse(
            close=True,
            extra=(
                f"htmx.ajax('GET', '{url}', {{target: '#settings-content', "
                f"select: '#form-layout-view', swap: 'innerHTML'}})"
                f".then(function () {{ history.pushState({{}}, '', '{url}'); }});"
            ),
        )


class FormLayoutEditorMixin:
    """Shared model selection and context for the layout editor."""

    editor_template_name = "field_management/form_layouts/layout_editor.html"

    def get_selected_model(self, request, strict=False):
        """
        Return the ``(content_type, model)`` named by the URL, or by the
        ``model`` parameter.

        An unknown or unregistered value returns ``(None, None)`` so a read
        never shows, and a write never lands on, a model the admin did not pick.
        """
        requested = (
            self.kwargs.get("ct")
            or request.POST.get("model")
            or request.GET.get("model")
        )
        for model in get_configurable_models():
            content_type = HorillaContentType.objects.get_for_model(model)
            if str(content_type.pk) == str(requested):
                return content_type, model
        return None, None

    def get_editor_context(
        self, request, content_type, model, entries=None, mode=MODE_VIEW
    ):
        """Build the template context for the editor partial."""
        can_change = request.user.has_perm(CHANGE_PERM)
        if model is not None and entries is None:
            entries = build_layout_entries(model, request)
        entries = entries or []
        return {
            "selected_content_type": content_type,
            "selected_label": str(model._meta.verbose_name) if model else "",
            "entries": entries,
            "visible_count": sum(1 for entry in entries if entry.visible),
            "total_count": len(entries),
            "has_layout": model is not None and get_form_layout(model) is not None,
            "is_editing": mode == MODE_EDIT and can_change and model is not None,
            "can_change": can_change,
            "can_reset": request.user.has_perm(DELETE_PERM),
        }

    def render_editor(
        self,
        request,
        content_type,
        model,
        template_name=None,
        mode=MODE_VIEW,
        entries=None,
    ):
        """Render the editor (or the full page) for ``model``."""
        if model is None:
            raise Http404
        context = self.get_editor_context(
            request, content_type, model, entries=entries, mode=mode
        )
        return render(request, template_name or self.editor_template_name, context)


@method_decorator(
    permission_required_or_denied(VIEW_PERM, wrapper_id="form-layout-view"),
    name="dispatch",
)
class FormLayoutView(LoginRequiredMixin, FormLayoutEditorMixin, View):
    """Detail page for one model's layout; always opens read-only."""

    template_name = "field_management/form_layouts/form_layout_view.html"

    def get(self, request, *args, **kwargs):
        """Render the detail page with the read-only editor."""
        content_type, model = self.get_selected_model(request)
        return self.render_editor(
            request, content_type, model, template_name=self.template_name
        )


@method_decorator(htmx_required, name="dispatch")
@method_decorator(permission_required(VIEW_PERM), name="dispatch")
class FormLayoutDetailNavbar(LoginRequiredMixin, FormLayoutEditorMixin, HorillaNavView):
    """Horilla navbar of a layout's detail page: title, Edit Layout and Delete."""

    nav_description = _(
        "Choose which fields appear and in what order. "
        "Available as a Custom Layout mode on create and edit forms."
    )
    main_url = reverse_lazy("field_management:form_layout_view")
    one_view_only = True
    all_view_types = False
    reload_option = False
    filter_option = False
    search_option = False
    recently_viewed_option = False
    nav_width = False
    navbar_indication = True
    model_name = "FormLayoutField"
    model_app_label = "field_management"

    def get_navbar_indication_attrs(self):
        """Back arrow to the layouts list."""
        return {
            "hx-get": str(reverse("field_management:form_layout_view")),
            "hx-target": "#settings-content",
            "hx-select": "#form-layout-view",
            "hx-swap": "innerHTML",
            "hx-push-url": "true",
            "title": str(_("All form layouts")),
        }

    @cached_property
    def selected(self):
        """The ``(content_type, model)`` pair named in the URL."""
        return self.get_selected_model(self.request)

    @property
    def nav_title(self):
        """Title with the model's name."""
        _content_type, model = self.selected
        if model is None:
            raise Http404
        return _("%(model)s Form Layout") % {"model": model._meta.verbose_name}

    @property
    def is_editing(self):
        """True while the layout editor is open (``?mode=edit``)."""
        return self.request.GET.get("mode") == MODE_EDIT and self.request.user.has_perm(
            CHANGE_PERM
        )

    @cached_property
    def new_button(self):
        """Save while editing, otherwise Edit Layout, for users who may change."""
        content_type, _model = self.selected
        if not self.request.user.has_perm(CHANGE_PERM):
            return None
        if self.is_editing:
            return {
                "url": reverse("field_management:form_layout_save"),
                "title": _("Save Layout"),
                "onclick": "document.getElementById('form-layout-form').requestSubmit()",
                # never fires: the click submits the editor form
                "attrs": {"hx-trigger": "never"},
            }
        return {
            "url": reverse(
                "field_management:form_layout_edit", kwargs={"ct": content_type.pk}
            ),
            "title": _("Edit Layout"),
            "target": "#form-layout-editor",
            "swap": "outerHTML",
            "onclick": "void(0)",
        }

    @cached_property
    def second_button(self):
        """Cancel while editing, otherwise Delete, for users who may remove."""
        content_type, _model = self.selected
        if self.is_editing:
            return {
                "url": reverse("field_management:form_layout_save"),
                "title": _("Cancel"),
                "onclick": "window.horillaFormLayouts.cancel(this)",
                "attrs": {
                    # never fires: the click is handled by horillaFormLayouts.cancel()
                    "hx-trigger": "never",
                    "data-layout-cancel": "",
                    "data-cancel-url": "%s?model=%s"
                    % (reverse("field_management:form_layout_editor"), content_type.pk),
                    "data-confirm": _("Discard your unsaved changes?"),
                },
            }
        if not self.request.user.has_perm(DELETE_PERM):
            return None
        reset_url = reverse("field_management:form_layout_reset")
        return {
            "url": reset_url,
            "title": _("Delete"),
            "onclick": "formLayoutDelete(this)",
            "attrs": {
                # never fires: the click is handled by formLayoutDelete()
                "hx-trigger": "never",
                "data-url": reset_url,
                "data-model": content_type.pk,
                "data-confirm": _(
                    "Delete this form layout? The create form goes back to the default."
                ),
            },
        }


@method_decorator(htmx_required, name="dispatch")
@method_decorator(permission_required_or_denied(VIEW_PERM), name="dispatch")
class FormLayoutEditorView(LoginRequiredMixin, FormLayoutEditorMixin, View):
    """
    Editor partial: enters edit mode or cancels editing

    ``?mode=edit`` opens edit mode for users with change permission; everyone
    else, and any other value, gets the read-only view.
    """

    forced_mode = None

    def get(self, request, *args, **kwargs):
        """Render the editor for the requested model and mode."""
        requested = self.forced_mode or request.GET.get("mode")
        mode = MODE_EDIT if requested == MODE_EDIT else MODE_VIEW
        content_type, model = self.get_selected_model(request)
        return self.render_editor(request, content_type, model, mode=mode)


@method_decorator(htmx_required, name="dispatch")
@method_decorator(permission_required_or_denied(CHANGE_PERM), name="dispatch")
class FormLayoutSaveView(LoginRequiredMixin, FormLayoutEditorMixin, View):
    """Store the submitted field order and visibility for one model."""

    def post(self, request, *args, **kwargs):
        """Save the layout and return to the read-only detail view."""
        content_type, model = self.get_selected_model(request, strict=True)
        if model is None:
            raise Http404

        entries = save_form_layout(
            model,
            ordered_names=request.POST.getlist("field_order"),
            visible_names=request.POST.getlist("visible"),
            full_width_names=request.POST.getlist("full_width"),
            company=getattr(request, "active_company", None),
            request=request,
        )
        messages.success(request, _("Create form layout saved."))
        return self.render_editor(request, content_type, model, entries=entries)


@method_decorator(htmx_required, name="dispatch")
@method_decorator(permission_required_or_denied(DELETE_PERM), name="dispatch")
class FormLayoutResetView(LoginRequiredMixin, FormLayoutEditorMixin, View):
    """Remove a model's layout so its create form goes back to the default."""

    def post(self, request, *args, **kwargs):
        """Delete the stored layout and go back to the layouts list."""
        content_type, model = self.get_selected_model(request, strict=True)
        if model is None:
            raise Http404

        reset_form_layout(
            model, getattr(request, "active_company", None), request=request
        )
        messages.success(request, _("Create form reset to the default layout."))
        response = HttpResponse()
        response["HX-Redirect"] = reverse("field_management:form_layout_view")
        return response
