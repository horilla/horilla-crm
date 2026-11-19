"""
Reusable inline "Edit Details" for a single record.

``HorillaInlineEditMixin`` renders a record as read-only sections and swaps
them for the model's form in place; ``HorillaInlineEditNavMixin`` gives the
page's generic navbar the matching Edit Details / Cancel / Save buttons.

The sections come from the form class's ``fieldsets``, so a page only names
a model, a form class and its templates.
"""

# Third-party imports (Django)
from django.contrib import messages
from django.core.exceptions import FieldDoesNotExist

# First party imports (Horilla)
from horilla.db import models
from horilla.shortcuts import get_object_or_404, render
from horilla.urls import reverse_lazy
from horilla.utils.functional import cached_property
from horilla.utils.translation import gettext_lazy as _
from horilla.web import ScriptResponse

FILE_FIELD_TYPES = (models.FileField, models.ImageField)


class HorillaInlineEditMixin:
    """
    Read-only sections that switch to an inline form for one record.

    Use with ``TemplateView``. Set ``model``, ``form_class`` (a
    ``HorillaModelForm`` with ``fieldsets``) and ``template_name``; the
    template receives ``obj``, ``sections``, ``form`` (None when reading),
    ``saved`` and ``can_change`` and can include
    ``partials/inline_edit_view_sections.html`` /
    ``partials/inline_edit_form_sections.html``.

    ``edit`` opens the form straight away (e.g. ``as_view(edit=True)``);
    otherwise ``?edit=true`` does. Override ``get_object``, ``after_save``
    and ``on_saved`` to customize.
    """

    model = None
    form_class = None
    edit = False
    change_perm = None
    success_message = _("Details updated successfully.")
    # Form-only fields shown when reading: ``{field_name: label}``, drawn by
    # ``form_only_template`` (which gets ``field_name`` and the extra context).
    form_only_fields = {}
    form_only_template = ""

    def get_object(self):
        """The record named by ``pk`` in the URL."""
        return get_object_or_404(self.model, pk=self.kwargs["pk"])

    def can_change(self):
        """Whether the user may edit the record."""
        perm = self.change_perm or (
            f"{self.model._meta.app_label}.change_{self.model._meta.model_name}"
        )
        return self.request.user.has_perm(perm)

    def get_sections(self, obj):
        """Return ``(title, [(label, field_name)])``; file fields are form-only."""
        sections = []
        for title, options in self.form_class.fieldsets:
            rows = []
            for name in options["fields"]:
                try:
                    field = obj._meta.get_field(name)
                except FieldDoesNotExist:
                    # A form-only field is shown by ``form_only_template``.
                    if name in self.form_only_fields:
                        rows.append((self.form_only_fields[name], name))
                    continue
                if not isinstance(field, FILE_FIELD_TYPES):
                    rows.append((field.verbose_name, name))
            if rows:
                sections.append((title, rows))
        return sections

    def render_inline(self, request, obj, form=None, saved=False):
        """Render read-only sections, or the form when one is given."""
        context = {
            "obj": obj,
            "sections": self.get_sections(obj),
            "form": form,
            "saved": saved,
            "can_change": self.can_change(),
            "bool_values": self.get_bool_values(obj),
            "form_only_fields": list(self.form_only_fields),
            "form_only_template": self.form_only_template,
            **self.get_extra_context(obj),
        }
        return render(request, self.template_name, context)

    def get_bool_values(self, obj):
        """
        ``{field_name: label}`` for the yes/no fields of ``obj``, worded as the form's
        ``boolean_labels`` (Yes / No when it gives none), so the read-only view
        says the same as the switch in the form.
        """
        labels = getattr(self.form_class, "boolean_labels", None) or {}
        values = {}
        for _title, options in self.form_class.fieldsets:
            for name in options["fields"]:
                try:
                    field = obj._meta.get_field(name)
                except FieldDoesNotExist:
                    continue
                if isinstance(field, models.BooleanField):
                    true_label, false_label = labels.get(name, (_("Yes"), _("No")))
                    values[name] = true_label if getattr(obj, name) else false_label
        return values

    def get_extra_context(self, obj):
        """Extra template context for ``obj``; override to add more."""
        return {}

    def get(self, request, *args, **kwargs):
        """Render read-only, or the form when ``edit`` / ``?edit=true`` is set."""
        obj = self.get_object()
        form = None
        wants_edit = self.edit or request.GET.get("edit") == "true"
        if wants_edit and self.can_change():
            form = self.form_class(instance=obj, request=request)
        return self.render_inline(request, obj, form=form)

    def post(self, request, *args, **kwargs):
        """Validate and save the form, or re-render it with errors."""
        obj = self.get_object()
        if not self.can_change():
            messages.error(request, _("You do not have permission to edit this."))
            return ScriptResponse(reload=True, status=403)
        form = self.form_class(
            request.POST, request.FILES, instance=obj, request=request
        )
        if not form.is_valid():
            return self.render_inline(request, obj, form=form)
        obj = form.save()
        self.clear_removed_files(request, form, obj)
        self.after_save(request, obj)
        messages.success(request, self.success_message)
        return self.on_saved(request, obj)

    def clear_removed_files(self, request, form, obj):
        """Delete file fields whose "Remove photo" was used without a new upload."""
        cleared = []
        for model_field in obj._meta.fields:
            name = model_field.name
            if not isinstance(model_field, FILE_FIELD_TYPES) or name not in form.fields:
                continue
            if request.POST.get(f"id_{name}_clear") == "true" and not request.FILES.get(
                name
            ):
                getattr(obj, name).delete(save=False)
                setattr(obj, name, None)
                cleared.append(name)
        if cleared:
            obj.save()

    def after_save(self, request, obj):
        """Hook run after a successful save (signals, side effects)."""

    def on_saved(self, request, obj):
        """Response after a successful save; default is the read-only sections."""
        return self.render_inline(request, obj, saved=True)


class HorillaInlineEditNavMixin:
    """
    Navbar buttons for a page using :class:`HorillaInlineEditMixin`.

    Use with ``HorillaNavView``. Shows **Edit** while reading and
    **Cancel** / **Save** while ``?mode=edit``. Set ``content_url_name`` (the
    content view), ``edit_url_name`` (its ``edit=True`` twin) and
    ``content_target`` (the id of the swapped element); ``form_id`` is the
    inline form's id. Override ``get_nav_object`` to resolve the record.
    """

    model = None
    content_url_name = ""
    edit_url_name = ""
    content_target = "#inline-edit-content"
    form_id = "inline-edit-form"
    change_perm = None
    nav_width = False
    one_view_only = True
    all_view_types = False
    reload_option = False
    filter_option = False
    search_option = False
    recently_viewed_option = False

    def get_nav_object(self):
        """The record named by ``pk`` in the URL."""
        return get_object_or_404(self.model, pk=self.kwargs["pk"])

    @cached_property
    def nav_object(self):
        """The record, resolved once per request."""
        return self.get_nav_object()

    def can_change(self):
        """Whether the user may edit the record."""
        perm = self.change_perm or (
            f"{self.model._meta.app_label}.change_{self.model._meta.model_name}"
        )
        return self.request.user.has_perm(perm)

    @property
    def is_editing(self):
        """True while the inline form is open (``?mode=edit``)."""
        return self.request.GET.get("mode") == "edit" and self.can_change()

    @cached_property
    def new_button(self):
        """Save while editing, otherwise Edit Details."""
        if not self.can_change():
            return None
        pk = self.nav_object.pk
        if self.is_editing:
            return {
                "url": reverse_lazy(self.content_url_name, kwargs={"pk": pk}),
                "title": _("Save"),
                "onclick": f"document.getElementById('{self.form_id}').requestSubmit()",
                # never fires: the click submits the inline form
                "attrs": {"hx-trigger": "never"},
            }
        return {
            "url": reverse_lazy(self.edit_url_name, kwargs={"pk": pk}),
            "title": _("Edit"),
            "target": self.content_target,
            "swap": "outerHTML",
            "onclick": "void(0)",
        }

    @cached_property
    def second_button(self):
        """Cancel while editing."""
        if not self.is_editing:
            return None
        return {
            "url": reverse_lazy(
                self.content_url_name, kwargs={"pk": self.nav_object.pk}
            ),
            "title": _("Cancel"),
            "target": self.content_target,
            "swap": "outerHTML",
            "onclick": "void(0)",
        }
