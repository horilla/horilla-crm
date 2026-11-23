"""Preview and draft views (preview, check changes, save, discard)."""

# Standard library imports
import logging
import re

# Third-party imports (Django)
from django.contrib import messages
from django.utils.safestring import mark_safe

from horilla.apps import apps

# First party imports (Horilla)
from horilla.auth.mixins import LoginRequiredMixin
from horilla.contrib.core.models import HorillaContentType
from horilla.contrib.generics.views.details import check_record_access
from horilla.contrib.utils.methods import has_ssti, has_xss, sanitize_html
from horilla.contrib.utils.middlewares import get_active_company
from horilla.shortcuts import render
from horilla.utils.decorators import (
    htmx_required,
    method_decorator,
    permission_required_or_denied,
)
from horilla.utils.html import format_html
from horilla.utils.translation import gettext as _
from horilla.views.generic import View
from horilla.web import HttpResponse

# Local imports
from ...models import HorillaMail, HorillaMailAttachment, HorillaMailConfiguration

logger = logging.getLogger(__name__)


def _sanitize_html(content):
    return mark_safe(sanitize_html(content))


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied(
        [
            "mail.view_horillamail",
            "mail.view_own_horillamail",
        ]
    ),
    name="dispatch",
)
class HorillaMailPreviewView(LoginRequiredMixin, View):
    """
    Preview mail content using existing draft mail object and its render methods
    """

    def get(self, request, *args, **kwargs):
        """
        Render preview of the mail
        """

        pk = self.kwargs.get("pk")
        draft_mail = HorillaMail.objects.filter(pk=pk).first()
        if not draft_mail:
            return HttpResponse(status=404)
        if not request.user.has_perm("mail.view_horillamail"):
            if draft_mail.created_by != request.user:
                return render(request, "403.html", status=403)
        from_mail_config = None
        if draft_mail.sender_id:
            try:
                from_mail_config = HorillaMailConfiguration.objects.get(
                    id=draft_mail.sender_id
                )
            except HorillaMailConfiguration.DoesNotExist:
                pass

        attachments = []
        inline_attachments = {}

        existing_attachments = HorillaMailAttachment.objects.filter(
            mail=draft_mail.pk,
        )
        for attachment in existing_attachments:
            if attachment.is_inline:
                # Store inline attachments by their content_id for replacement
                if attachment.content_id:
                    inline_attachments[attachment.content_id] = attachment
                # Also store by filename as fallback
                inline_attachments[attachment.file_name()] = attachment
            else:
                attachments.append(attachment)

        # Use the snapshot saved at send time when available so that
        # insert-field variables (e.g. {{ request.user.first_name }}) reflect
        # the sender's context, not the current viewer's.
        rendered_subject = draft_mail.rendered_subject or draft_mail.render_subject()
        rendered_body = draft_mail.rendered_body or draft_mail.render_body()

        # Pattern to find cid: in src attributes and capture data-filename if present
        cid_pattern = re.compile(
            r'<img\s+([^>]*?)src=["\']cid:([^"\']+)["\']([^>]*?)>', re.IGNORECASE
        )

        def replace_cid(match):
            before_src = match.group(1)
            content_id = match.group(2)
            after_src = match.group(3)

            # Try to find by content_id first
            if content_id in inline_attachments:
                attachment = inline_attachments[content_id]
                return f'<img {before_src}src="{attachment.file.url}"{after_src}>'

            # Try to find by filename from data-filename attribute
            filename_match = re.search(
                r'data-filename=["\']([^"\']+)["\']', before_src + after_src
            )
            if filename_match:
                filename = filename_match.group(1)
                if filename in inline_attachments:
                    attachment = inline_attachments[filename]
                    return f'<img {before_src}src="{attachment.file.url}"{after_src}>'

            return match.group(0)  # Return original if not found

        rendered_body = cid_pattern.sub(replace_cid, rendered_body)

        preview_context = {
            "draft_mail": draft_mail,
            "to_email": draft_mail.to,
            "cc_email": draft_mail.cc,
            "bcc_email": draft_mail.bcc,
            "subject": rendered_subject,
            "message_content": _sanitize_html(rendered_body),
            "from_mail_config": from_mail_config,
            "attachments": attachments,
            "draft": False,
        }
        return render(request, "mail_preview_modal.html", preview_context)

    def post(self, request, *args, **kwargs):
        """
        Generate preview based on form data without saving
        """
        try:
            # Get form data
            to_email = request.POST.get("to_email", "")
            cc_email = request.POST.get("cc_email", "")
            bcc_email = request.POST.get("bcc_email", "")
            subject = request.POST.get("subject", "")
            message_content = request.POST.get("message_content", "")
            from_mail_id = request.POST.get("from_mail")
            uploaded_files = request.FILES.getlist("attachments")

            model_name = request.GET.get("model_name")
            pk = request.GET.get("pk")
            object_id = request.GET.get("object_id")

            from_mail_config = None
            if from_mail_id:
                try:
                    from_mail_config = HorillaMailConfiguration.objects.get(
                        id=from_mail_id
                    )
                except HorillaMailConfiguration.DoesNotExist:
                    pass

            draft_mail = None
            content_type = None

            if model_name and object_id:
                try:
                    content_type = HorillaContentType.objects.get(
                        model=model_name.lower()
                    )
                    draft_mail = HorillaMail.objects.filter(pk=pk).first()
                except Exception as e:
                    logger.error("Error finding draft mail: %s", e)

            if not draft_mail:
                company = get_active_company(request)
                draft_mail = HorillaMail(
                    content_type=content_type,
                    object_id=object_id or 0,
                    mail_status="draft",
                    created_by=request.user,
                    sender=from_mail_config,
                    company=company,
                )

            # Validate subject and body for XSS and SSTI before any rendering
            if has_xss(subject) or has_ssti(subject):
                return render(
                    request,
                    "mail_preview_error.html",
                    {"error_message": _("Subject contains dangerous content.")},
                )
            # The body is HTML from a rich-text editor so has_xss will always fire
            # on normal tags like <p>. Only check for SSTI (template injection) here;
            # HTML is sanitized by sanitize_html before rendering.
            if has_ssti(message_content):
                return render(
                    request,
                    "mail_preview_error.html",
                    {"error_message": _("Message body contains dangerous content.")},
                )

            draft_mail.sender = from_mail_config
            draft_mail.to = to_email
            draft_mail.cc = cc_email if cc_email else None
            draft_mail.bcc = bcc_email if bcc_email else None
            draft_mail.subject = subject
            draft_mail.body = message_content

            # request is needed for {{ request.user.first_name }} insert-field variables.
            # Dangerous paths (request.META, request.session, password, etc.)
            # are blocked earlier by has_ssti().
            template_context = {
                "request": request,
                "user": request.user,
            }

            active_company = get_active_company(request)
            if active_company:
                template_context["active_company"] = active_company

            if content_type and object_id:
                try:
                    model_class = apps.get_model(
                        app_label=content_type.app_label, model_name=content_type.model
                    )
                    # IDOR fix: verify the requesting user has view permission
                    # for this model before loading the object
                    perm = f"{content_type.app_label}.view_{content_type.model}"
                    related_object = model_class.objects.get(pk=object_id)
                    if not request.user.has_perm(perm):
                        # Fall back to ownership check via OWNER_FIELDS
                        owner_fields = getattr(model_class, "OWNER_FIELDS", [])
                        is_owner = any(
                            getattr(related_object, f, None) == request.user
                            for f in owner_fields
                        )
                        if not is_owner:
                            logger.warning(
                                "User %s attempted to access %s pk=%s without permission",
                                request.user,
                                content_type.model,
                                object_id,
                            )
                            return render(
                                request,
                                "mail_preview_error.html",
                                {
                                    "error_message": _(
                                        "You do not have permission to access this record."
                                    )
                                },
                            )
                    template_context["instance"] = related_object
                    draft_mail.related_to = related_object
                except Exception as e:
                    logger.error("Error getting related object: %s", e)

            rendered_subject = ""
            rendered_content = ""

            try:
                rendered_subject = draft_mail.render_subject(template_context)
            except Exception as e:
                rendered_subject = f"[Template Error in Subject: {str(e)}] {subject}"

            try:
                rendered_content = draft_mail.render_body(template_context)
            except Exception as e:
                rendered_content = (
                    format_html(
                        "<div class='text-red-500 text-sm'>[Template Error: {}]</div>",
                        str(e),
                    )
                    + message_content
                )

            attachments = []
            if draft_mail.pk:
                existing_attachments = HorillaMailAttachment.objects.filter(
                    mail=draft_mail.pk,
                )
                for attachment in existing_attachments:
                    attachments.append(attachment)
                for f in uploaded_files:
                    attachment = HorillaMailAttachment(
                        mail=draft_mail,
                        file=f,  # each file individually
                    )
                    attachment.save()
                    attachments.append(attachment)

            preview_context = {
                "draft_mail": draft_mail,
                "to_email": to_email,
                "cc_email": cc_email,
                "bcc_email": bcc_email,
                "subject": rendered_subject,
                "message_content": _sanitize_html(rendered_content),
                "from_mail_config": from_mail_config,
                "template_context": template_context,
                "attachments": attachments,
            }

            return render(request, "mail_preview_modal.html", preview_context)

        except Exception as e:
            return render(request, "mail_preview_error.html", {"error_message": str(e)})


@method_decorator(htmx_required, name="dispatch")
class CheckDraftChangesView(LoginRequiredMixin, View):
    """
    Check if there are changes to save and return appropriate modal content
    """

    def dispatch(self, request, *args, **kwargs):
        """Require access to the related record before checking draft changes."""
        user = request.user
        if user.is_superuser:
            return super().dispatch(request, *args, **kwargs)
        model_name = request.GET.get("model_name")
        object_id = request.GET.get("object_id")
        pk = request.GET.get("pk")
        if model_name and object_id:
            try:
                ct = HorillaContentType.objects.get(model=model_name.lower())
                model_class = apps.get_model(ct.app_label, ct.model)
                related_obj = model_class.objects.get(pk=object_id)
                if check_record_access(user, related_obj):
                    return super().dispatch(request, *args, **kwargs)
            except Exception:
                pass
        if pk:
            try:
                draft = HorillaMail.objects.get(pk=pk)
                if draft.content_type and draft.object_id:
                    model_class = apps.get_model(
                        draft.content_type.app_label, draft.content_type.model
                    )
                    related_obj = model_class.objects.get(pk=draft.object_id)
                    if check_record_access(user, related_obj):
                        return super().dispatch(request, *args, **kwargs)
            except Exception:
                pass
        return render(request, "403.html", status=403)

    def post(self, request, *args, **kwargs):
        """
        Always show confirmation modal when closing - user can choose to save or discard
        """
        model_name = request.GET.get("model_name")
        pk = request.GET.get("pk")
        object_id = request.GET.get("object_id")

        # Always show confirmation modal when closing
        return render(
            request,
            "draft_save_modal.html",
            {"model_name": model_name, "object_id": object_id, "pk": pk},
        )


class SaveDraftView(LoginRequiredMixin, View):
    """
    Save the current mail as draft
    """

    def dispatch(self, request, *args, **kwargs):
        """Require access to the related record before saving a draft."""
        user = request.user
        if not user.is_authenticated:
            return super().dispatch(request, *args, **kwargs)
        if user.is_superuser:
            return super().dispatch(request, *args, **kwargs)
        model_name = request.GET.get("model_name")
        object_id = request.GET.get("object_id")
        if model_name and object_id:
            try:
                ct = HorillaContentType.objects.get(model=model_name.lower())
                model_class = apps.get_model(ct.app_label, ct.model)
                related_obj = model_class.objects.get(pk=object_id)
                if check_record_access(user, related_obj):
                    return super().dispatch(request, *args, **kwargs)
            except Exception:
                pass
        return render(request, "403.html", status=403)

    def post(self, request, *args, **kwargs):
        """
        Save draft mail
        """
        try:
            to_email = request.POST.get("to_email", "").strip()
            cc_email = request.POST.get("cc_email", "").strip()
            bcc_email = request.POST.get("bcc_email", "").strip()
            subject = request.POST.get("subject", "").strip()
            message_content = request.POST.get("message_content", "").strip()
            from_mail_id = request.POST.get("from_mail")
            uploaded_files = request.FILES.getlist("attachments")
            model_name = request.GET.get("model_name")
            object_id = request.GET.get("object_id")
            company = get_active_company(request)
            pk = request.GET.get("pk")

            # Normalize empty HTML content (like <p><br></p> or <p></p>)
            def normalize_html_content(content):
                if not content:
                    return ""
                # Remove common empty HTML patterns
                normalized = content.strip()
                normalized = re.sub(
                    r"<p>\s*<br\s*/?>\s*</p>", "", normalized, flags=re.IGNORECASE
                )
                normalized = re.sub(r"<p>\s*</p>", "", normalized, flags=re.IGNORECASE)
                normalized = normalized.strip()
                return normalized

            normalized_message = normalize_html_content(message_content)

            # Get existing draft if pk exists
            draft_mail = None
            if pk:
                try:
                    draft_mail = HorillaMail.objects.get(
                        pk=pk,
                        mail_status="draft",
                        created_by=request.user,
                    )
                except HorillaMail.DoesNotExist:
                    pass

            # Check if there are actual changes
            has_changes = False

            if draft_mail:
                # Compare with existing draft
                draft_body = normalize_html_content(draft_mail.body or "")
                draft_to = (draft_mail.to or "").strip()
                draft_cc = (draft_mail.cc or "").strip()
                draft_bcc = (draft_mail.bcc or "").strip()
                draft_subject = (draft_mail.subject or "").strip()
                draft_from_id = (
                    str(draft_mail.sender_id) if draft_mail.sender_id else ""
                )

                if (
                    to_email != draft_to
                    or cc_email != draft_cc
                    or bcc_email != draft_bcc
                    or subject != draft_subject
                    or normalized_message != draft_body
                    or (from_mail_id and from_mail_id != draft_from_id)
                ):
                    has_changes = True
            else:
                # New draft - check if there's any actual content (not just empty HTML)
                has_changes = any(
                    [to_email, cc_email, bcc_email, subject, normalized_message]
                )

            # Check for new attachments
            if request.FILES.getlist("attachments"):
                has_changes = True

            # Only save if there are actual changes
            if not has_changes:
                messages.success(request, _("Draft saved successfully"))
                return HttpResponse(
                    "<script>closehorillaModal();"
                    "$('#draft-email-tab').click();"
                    "closeDeleteModeModal();</script>"
                )

            # Get or create mail configuration
            from_mail_config = None
            if from_mail_id:
                try:
                    from_mail_config = HorillaMailConfiguration.objects.get(
                        id=from_mail_id
                    )
                except HorillaMailConfiguration.DoesNotExist:
                    from_mail_config = HorillaMailConfiguration.objects.filter(
                        is_primary=True
                    ).first()

            if not from_mail_config:
                from_mail_config = HorillaMailConfiguration.objects.first()

            # Get content type
            content_type = None
            if model_name and object_id:
                try:
                    content_type = HorillaContentType.objects.get(
                        model=model_name.lower()
                    )
                except HorillaContentType.DoesNotExist:
                    pass

            # Find or create draft (if we don't already have it from change detection)
            if not draft_mail:
                if content_type and object_id:
                    draft_mail = HorillaMail.objects.filter(
                        pk=pk,
                        content_type=content_type,
                        object_id=object_id,
                        mail_status="draft",
                        created_by=request.user,
                    ).first()

            if not draft_mail:
                draft_mail = HorillaMail.objects.create(
                    content_type=content_type,
                    object_id=object_id,
                    mail_status="draft",
                    created_by=request.user,
                    sender=from_mail_config,
                    company=company,
                )

            # Update draft with current data
            if from_mail_config:
                draft_mail.sender = from_mail_config
            draft_mail.to = to_email
            draft_mail.cc = cc_email if cc_email else None
            draft_mail.bcc = bcc_email if bcc_email else None
            draft_mail.subject = subject
            draft_mail.body = message_content
            draft_mail.save()
            if draft_mail.pk:
                for f in uploaded_files:
                    attachment = HorillaMailAttachment(
                        mail=draft_mail, file=f, company=company
                    )
                    attachment.save()
            messages.success(request, _("Draft saved successfully"))
            return HttpResponse(
                "<script>closehorillaModal();"
                "$('#draft-email-tab').click();"
                "closeDeleteModeModal();</script>"
            )

        except Exception as e:
            messages.error(request, _("Error saving draft: ") + str(e))
            return HttpResponse(
                "<script>closehorillaModal();"
                "htmx.trigger('#draft-email-tab','click');"
                "closeDeleteModeModal();</script>"
            )


class DiscardDraftView(LoginRequiredMixin, View):
    """
    Discard the draft without saving
    """

    def dispatch(self, request, *args, **kwargs):
        """Require access to the related record before discarding a draft."""
        user = request.user
        if not user.is_authenticated:
            return super().dispatch(request, *args, **kwargs)
        if user.is_superuser:
            return super().dispatch(request, *args, **kwargs)
        model_name = request.GET.get("model_name")
        object_id = request.GET.get("object_id")
        if model_name and object_id:
            try:
                ct = HorillaContentType.objects.get(model=model_name.lower())
                model_class = apps.get_model(ct.app_label, ct.model)
                related_obj = model_class.objects.get(pk=object_id)
                if check_record_access(user, related_obj):
                    return super().dispatch(request, *args, **kwargs)
            except Exception:
                pass
        return render(request, "403.html", status=403)

    def delete(self, request, *args, **kwargs):
        """
        Discard draft mail
        """
        try:
            model_name = request.GET.get("model_name")
            object_id = request.GET.get("object_id")
            pk = pk = request.GET.get("pk")

            if model_name and object_id:
                try:
                    content_type = HorillaContentType.objects.get(
                        model=model_name.lower()
                    )
                    HorillaMail.objects.filter(
                        pk=pk,
                        content_type=content_type,
                        object_id=object_id,
                        mail_status="draft",
                        created_by=request.user,
                    ).delete()
                except HorillaContentType.DoesNotExist:
                    pass

            messages.info(request, _("Draft discarded"))
            return HttpResponse(
                "<script>closehorillaModal();"
                "$('#draft-email-tab').click();"
                "closeDeleteModeModal();</script>"
            )

        except Exception as e:
            messages.error(request, _("Error discarding draft: ") + str(e))
            return HttpResponse(
                "<script>closehorillaModal();"
                "htmx.trigger('#sent-email-tab','click');"
                "closeDeleteModeModal();</script>"
            )
