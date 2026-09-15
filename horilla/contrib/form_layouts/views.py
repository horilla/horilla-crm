"""
Settings views for per-company create form layouts.

Lets an admin choose, per company, which fields of an opted-in model appear on
its create form and in what order, without changing the model or its forms.

The editor opens read-only. Admins with change permission switch it into edit
mode explicitly, change visibility and order there, and save or cancel back to
the read-only view.
"""

# Third-party imports (Django)
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin

# First party imports (Horilla)
from horilla.contrib.core.models import HorillaContentType
from horilla.shortcuts import render
from horilla.utils.decorators import (
    htmx_required,
    method_decorator,
    permission_required_or_denied,
)
from horilla.utils.translation import gettext_lazy as _
from horilla.views.generic import View

# Local imports
from .registry import get_configurable_models
from .utils import (
    build_layout_entries,
    get_form_layout,
    reset_form_layout,
    save_form_layout,
)

MODE_VIEW = "view"
MODE_EDIT = "edit"


class FormLayoutEditorMixin:
    """Shared model selection and context for the layout editor."""

    editor_template_name = "form_layouts/layout_editor.html"

    def get_model_choices(self):
        """Return ``(content_type, model)`` pairs for the opted-in models."""
        return [
            (HorillaContentType.objects.get_for_model(model), model)
            for model in get_configurable_models()
        ]

    def get_selected_model(self, request, choices, strict=False):
        """
        Return the ``(content_type, model)`` named by the ``model`` parameter.

        Falls back to the first opted-in model unless ``strict`` is set, in
        which case an unknown or missing value returns ``(None, None)`` so a
        write never lands on a model the admin did not pick.
        """
        requested = request.POST.get("model") or request.GET.get("model")
        for content_type, model in choices:
            if str(content_type.pk) == str(requested):
                return content_type, model
        if strict or not choices:
            return None, None
        return choices[0]

    def get_editor_context(
        self, request, choices, content_type, model, entries=None, mode=MODE_VIEW
    ):
        """Build the template context for the editor partial."""
        can_change = request.user.has_perm("form_layouts.change_formlayoutfield")
        if model is not None and entries is None:
            entries = build_layout_entries(model, request)
        entries = entries or []
        return {
            "model_choices": [
                {
                    "id": choice_ct.pk,
                    "label": str(choice_model._meta.verbose_name),
                    "selected": content_type is not None
                    and choice_ct.pk == content_type.pk,
                }
                for choice_ct, choice_model in choices
            ],
            "selected_content_type": content_type,
            "selected_label": str(model._meta.verbose_name) if model else "",
            "entries": entries,
            "visible_count": sum(1 for entry in entries if entry.visible),
            "total_count": len(entries),
            "has_layout": model is not None and get_form_layout(model) is not None,
            "is_editing": mode == MODE_EDIT and can_change and model is not None,
            "can_change": can_change,
            "can_reset": request.user.has_perm("form_layouts.delete_formlayoutfield"),
        }

    def render_editor(self, request, template_name=None, mode=MODE_VIEW, **kwargs):
        """Render the editor (or the full page) for the selected model."""
        choices = kwargs.pop("choices", None) or self.get_model_choices()
        if "model" in kwargs:
            content_type, model = kwargs.pop("content_type"), kwargs.pop("model")
        else:
            content_type, model = self.get_selected_model(request, choices)
        context = self.get_editor_context(
            request,
            choices,
            content_type,
            model,
            entries=kwargs.pop("entries", None),
            mode=mode,
        )
        return render(request, template_name or self.editor_template_name, context)


@method_decorator(
    permission_required_or_denied(
        "form_layouts.view_formlayoutfield",
        wrapper_id="form-layout-view",
    ),
    name="dispatch",
)
class FormLayoutView(LoginRequiredMixin, FormLayoutEditorMixin, View):
    """
    Settings page for create form layouts; always opens read-only
    """

    template_name = "form_layouts/form_layout_view.html"

    def get(self, request, *args, **kwargs):
        """Render the settings page with the read-only editor."""
        return self.render_editor(request, self.template_name)


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied("form_layouts.view_formlayoutfield"),
    name="dispatch",
)
class FormLayoutEditorView(LoginRequiredMixin, FormLayoutEditorMixin, View):
    """
    Editor partial: switches model, enters edit mode, or cancels editing

    ``?mode=edit`` opens edit mode for users with change permission; everyone
    else, and any other value, gets the read-only view.
    """

    def get(self, request, *args, **kwargs):
        """Render the editor for the requested model and mode."""
        mode = MODE_EDIT if request.GET.get("mode") == MODE_EDIT else MODE_VIEW
        return self.render_editor(request, mode=mode)


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied("form_layouts.change_formlayoutfield"),
    name="dispatch",
)
class FormLayoutSaveView(LoginRequiredMixin, FormLayoutEditorMixin, View):
    """
    Store the submitted field order and visibility for one model
    """

    def post(self, request, *args, **kwargs):
        """Save the layout and return to the read-only editor."""
        choices = self.get_model_choices()
        content_type, model = self.get_selected_model(request, choices, strict=True)
        if model is None:
            messages.error(request, _("Select a valid model."))
            return self.render_editor(request, choices=choices)

        entries = save_form_layout(
            model,
            ordered_names=request.POST.getlist("field_order"),
            visible_names=request.POST.getlist("visible"),
            company=getattr(request, "active_company", None),
            request=request,
        )
        messages.success(request, _("Create form layout saved."))
        return self.render_editor(
            request,
            choices=choices,
            content_type=content_type,
            model=model,
            entries=entries,
        )


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied("form_layouts.delete_formlayoutfield"),
    name="dispatch",
)
class FormLayoutResetView(LoginRequiredMixin, FormLayoutEditorMixin, View):
    """
    Remove a model's layout so its create form goes back to the default
    """

    def post(self, request, *args, **kwargs):
        """Delete the stored layout and return to the read-only editor."""
        choices = self.get_model_choices()
        content_type, model = self.get_selected_model(request, choices, strict=True)
        if model is None:
            messages.error(request, _("Select a valid model."))
            return self.render_editor(request, choices=choices)

        reset_form_layout(
            model, getattr(request, "active_company", None), request=request
        )
        messages.success(request, _("Create form reset to the default layout."))
        return self.render_editor(
            request, choices=choices, content_type=content_type, model=model
        )
