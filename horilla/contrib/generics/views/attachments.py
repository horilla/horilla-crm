"""
Views for managing notes and attachments in Horilla: the notes stream, in-place create and edit, pinning, and deletion.
These views handle permissions, rendering, and interactions for attachments related to various models in Horilla.
"""

# Standard library imports
import logging
from datetime import timedelta

# Third-party imports (Django)
from django.contrib import messages
from django.utils import timezone
from django.utils.formats import date_format

# First party imports (Horilla)
from horilla.auth.mixins import LoginRequiredMixin
from horilla.contrib.core.models import HorillaAttachment, HorillaContentType
from horilla.contrib.core.utils import get_allowed_user_ids
from horilla.contrib.utils.middlewares import get_active_company
from horilla.shortcuts import get_object_or_404, render
from horilla.urls import reverse_lazy
from horilla.utils.decorators import htmx_required, method_decorator
from horilla.utils.translation import gettext_lazy as _
from horilla.views.generic import DetailView, FormView, View
from horilla.web import HttpResponse, HxTriggerResponse, ScriptResponse

from ..forms import HorillaAttachmentForm

# Local imports
from ..history import (
    history_q,
    is_foreign_row,
    is_record_locked,
    parent_key,
    remember_history_parent,
)
from .delete import HorillaSingleDeleteView
from .details import (
    check_record_access,
    check_record_change_access,
    check_record_delete_access,
)

logger = logging.getLogger(__name__)


@method_decorator(htmx_required, name="dispatch")
class HorillaNotesAttachementSectionView(DetailView):
    """View for displaying notes and attachments section in detail views."""

    template_name = "notes_attachments.html"
    context_object_name = "obj"

    def get(self, request, *args, **kwargs):
        """Load attachment list for the detail object and render with add-permission flag."""
        self.object = self.get_object()
        if not check_record_access(request.user, self.object):
            return render(request, "403.html", status=403)
        queryset = HorillaAttachment.objects.filter(
            history_q(self.object, request.user)
        )
        remember_history_parent(request, self.object)

        user = request.user
        app = self.object._meta.app_label
        model_name = self.object._meta.model_name
        locked = is_record_locked(self.object)
        has_global_change = not locked and (
            user.is_superuser or user.has_perm(f"{app}.change_{model_name}")
        )
        has_global_delete = not locked and (
            user.is_superuser or user.has_perm(f"{app}.delete_{model_name}")
        )
        can_change_parent = has_global_change or check_record_change_access(
            user, self.object
        )
        can_delete_parent = has_global_delete or check_record_delete_access(
            user, self.object
        )
        allowed_ids = get_allowed_user_ids(user)

        def _owned(att):
            created_by = getattr(att, "created_by", None)
            return not created_by or created_by.pk in allowed_ids

        today = timezone.localdate()

        def _day_label(att):
            day = timezone.localtime(att.created_at).date()
            if day == today:
                return _("Today")
            if day == today - timedelta(days=1):
                return _("Yesterday")
            return date_format(day, "M d, Y")

        pinned, groups, total = [], [], 0
        for att in queryset.select_related("created_by").order_by("-created_at"):
            foreign = is_foreign_row(att, parent_key(self.object))
            writable = not locked and not foreign
            card = {
                "obj": att,
                "foreign": foreign,
                "can_edit": writable
                and can_change_parent
                and (has_global_change or _owned(att)),
                "can_delete": writable
                and can_delete_parent
                and (has_global_delete or _owned(att)),
                "can_pin": writable
                and can_change_parent
                and (has_global_change or _owned(att)),
                "kind": "file" if att.file else "note",
            }
            total += 1
            if att.is_pinned:
                pinned.append(card)
                continue
            label = _day_label(att)
            if not groups or groups[-1]["label"] != label:
                groups.append({"label": label, "cards": []})
            groups[-1]["cards"].append(card)
        if pinned:
            groups.insert(0, {"label": _("Pinned"), "cards": pinned, "pinned": True})

        context = super().get_context_data()
        context["attachment_groups"] = groups
        context["attachment_total"] = total
        context["can_add_attachment"] = can_change_parent
        if can_change_parent:
            context["form"] = HorillaAttachmentForm(inline=True)
            context["form_url"] = reverse_lazy("generics:notes_attachment_create")
            context["composer_query"] = (
                f"model_name={self.object.__class__.__name__}"
                f"&object_id={self.object.pk}&inline=1"
            )
        return render(request, self.template_name, context)


@method_decorator(htmx_required, name="dispatch")
class HorillaNotesAttachmentCreateView(LoginRequiredMixin, FormView):
    """View for creating new notes and attachments."""

    template_name = "forms/notes_attachment_composer.html"
    edit_template_name = "forms/notes_attachment_inline_edit.html"
    form_class = HorillaAttachmentForm
    model = HorillaAttachment

    def get_template_names(self):
        """Composer for new entries, the in-place editor for existing ones."""
        return [
            self.edit_template_name if self.kwargs.get("pk") else self.template_name
        ]

    def get_context_data(self, **kwargs):
        """Set form_url for create or edit based on pk."""
        context = super().get_context_data(**kwargs)
        context["form_url"] = reverse_lazy("generics:notes_attachment_create")
        context["composer_query"] = self.request.GET.urlencode()
        pk = self.kwargs.get("pk")
        if pk:
            context["form_url"] = reverse_lazy(
                "generics:notes_attachment_edit", kwargs={"pk": pk}
            )
        return context

    def get_object(self):
        """Return object if pk exists (for edit mode)."""
        pk = self.kwargs.get("pk")
        if pk:
            obj = get_object_or_404(HorillaAttachment, pk=pk)
            return obj
        return None

    def get_form(self, form_class=None):
        """Bind instance if editing."""
        form_class = self.get_form_class()
        obj = self.get_object()
        kwargs = self.get_form_kwargs()
        if obj:
            # Distinct ids so the in-place editor never clashes with the composer.
            kwargs["auto_id"] = f"edit_{obj.pk}_%s"
        return form_class(instance=obj, inline=True, **kwargs)

    def check_related_object_permission(self, related_object, permission_type="add"):
        """
        Allow add/change when user has change access on the parent record.
        For Change Own users editing a note, also verify the note's created_by
        is in the user's allowed set (own or subordinate).
        """
        user = self.request.user
        app = related_object._meta.app_label
        model = related_object._meta.model_name
        has_global_change = user.is_superuser or user.has_perm(f"{app}.change_{model}")
        if not (has_global_change or check_record_change_access(user, related_object)):
            return False
        if permission_type == "change" and not has_global_change:
            pk = self.kwargs.get("pk")
            if pk:
                try:
                    attachment = self.model.objects.get(pk=pk)
                    created_by = getattr(attachment, "created_by", None)
                    if created_by and created_by.pk not in get_allowed_user_ids(user):
                        return False
                except self.model.DoesNotExist:
                    pass
        return True

    def dispatch(self, request, *args, **kwargs):
        """Check permissions before processing the request."""
        # For edit mode, check if attachment exists and user has permission
        pk = kwargs.get("pk")
        if pk:
            try:
                attachment = self.model.objects.get(pk=pk)
                related_object = attachment.related_object

                if related_object:
                    if not self.check_related_object_permission(
                        related_object, "change"
                    ):
                        messages.error(
                            request,
                            _("You don't have permission to edit this attachment."),
                        )
                        return ScriptResponse(reload=True, msgs=True, close=True)
            except self.model.DoesNotExist:
                messages.error(request, _("The requested attachment does not exist."))
                return ScriptResponse(reload=True, msgs=True, close=True)

        # For create mode, check permission on the related object
        else:
            model_name = request.GET.get("model_name")
            object_id = request.GET.get("object_id")

            if model_name and object_id:
                try:
                    content_type = HorillaContentType.objects.get(
                        model=model_name.lower()
                    )
                    related_model = content_type.model_class()
                    related_object = related_model.objects.get(pk=object_id)

                    if not self.check_related_object_permission(related_object, "add"):
                        messages.error(
                            request,
                            _(
                                "You don't have permission to add attachments to this record."
                            ),
                        )
                        return ScriptResponse(reload=True, msgs=True, close=True)
                except (
                    HorillaContentType.DoesNotExist,
                    related_model.DoesNotExist,
                    ValueError,
                ):
                    messages.error(request, _("Invalid related object."))
                    return ScriptResponse(reload=True, msgs=True, close=True)

        return super().dispatch(request, *args, **kwargs)

    def form_valid(self, form):
        """Save attachment (create or update) and return close-modal/reload script."""
        model_name = self.request.GET.get("model_name")
        pk = self.kwargs.get("pk")

        attachment = form.save(commit=False)
        if not pk:
            content_type = HorillaContentType.objects.get(model=model_name.lower())
            attachment.created_by = self.request.user
            attachment.object_id = self.request.GET.get("object_id")
            attachment.content_type = content_type
            attachment.company = get_active_company(self.request)
        attachment.save()
        if pk:
            # Update only this entry so the stream keeps its scroll position.
            return render(
                self.request,
                "partials/notes_entry_bubble.html",
                {"att": attachment},
            )
        return HttpResponse("<script>$('#tab-notes-attachments').click();</script>")

    def get(self, request, *args, **kwargs):
        """Validate attachment pk when editing; then delegate to parent get."""
        pk = kwargs.get("pk")
        if pk:
            try:
                attachment = self.model.objects.get(pk=pk)
            except self.model.DoesNotExist:
                messages.error(request, _("The requested attachment does not exist."))
                return ScriptResponse(reload=True, msgs=True, close=True)
            if request.GET.get("view"):
                # Cancel in-place edit: show the entry again unchanged.
                return render(
                    request, "partials/notes_entry_bubble.html", {"att": attachment}
                )

        return super().get(request, *args, **kwargs)


@method_decorator(htmx_required, name="dispatch")
class HorillaNotesAttachmentPinView(LoginRequiredMixin, View):
    """Toggle the pinned flag of a note or attachment."""

    def post(self, request, pk):
        """Flip is_pinned when the user may change the entry, then reload the tab."""
        attachment = get_object_or_404(HorillaAttachment, pk=pk)
        related = attachment.related_object
        user = request.user
        allowed = False
        if related is not None and not is_record_locked(related):
            app = related._meta.app_label
            model = related._meta.model_name
            if user.is_superuser or user.has_perm(f"{app}.change_{model}"):
                allowed = True
            elif check_record_change_access(user, related):
                created_by = getattr(attachment, "created_by", None)
                allowed = not created_by or created_by.pk in get_allowed_user_ids(user)
        if not allowed:
            messages.error(
                request, _("You don't have permission to pin this attachment.")
            )
            return ScriptResponse(reload=True, msgs=True)
        attachment.is_pinned = not attachment.is_pinned
        attachment.save(update_fields=["is_pinned"])
        return HttpResponse("<script>$('#tab-notes-attachments').click();</script>")


@method_decorator(htmx_required, name="dispatch")
class HorillaNotesAttachmentDeleteView(LoginRequiredMixin, HorillaSingleDeleteView):
    """View for deleting notes and attachments."""

    model = HorillaAttachment
    check_delete_permission = False

    def dispatch(self, request, *args, **kwargs):
        """Allow delete only when user has change access on the parent record."""
        try:
            attachment = self.model.objects.get(pk=kwargs.get("pk"))
        except self.model.DoesNotExist:
            messages.error(request, _("The requested attachment does not exist."))
            return ScriptResponse(reload=True, msgs=True, close=True)

        user = request.user
        related_object = attachment.related_object
        if user.is_superuser:
            return super().dispatch(request, *args, **kwargs)

        if related_object:
            app = related_object._meta.app_label
            model = related_object._meta.model_name
            has_global_change = user.has_perm(f"{app}.change_{model}")
            if has_global_change or check_record_change_access(user, related_object):
                if has_global_change:
                    return super().dispatch(request, *args, **kwargs)
                created_by = getattr(attachment, "created_by", None)
                if not created_by or created_by.pk in get_allowed_user_ids(user):
                    return super().dispatch(request, *args, **kwargs)

        messages.error(
            request, _("You don't have permission to delete this attachment.")
        )
        return ScriptResponse(reload=True, msgs=True, close=True)

    def get_post_delete_response(self):
        return HxTriggerResponse(extra="closeContentModal();")
