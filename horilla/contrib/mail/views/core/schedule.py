"""Delete and schedule mail views."""

# Standard library imports
import logging
from datetime import datetime

# Third-party imports (Django)
from django.contrib import messages

from horilla.apps import apps

# First party imports (Horilla)
from horilla.auth.mixins import LoginRequiredMixin
from horilla.contrib.core.models import HorillaContentType
from horilla.contrib.generics.views import HorillaSingleDeleteView
from horilla.contrib.generics.views.details import check_record_access
from horilla.contrib.utils.middlewares import _thread_local, get_active_company
from horilla.shortcuts import get_object_or_404, render
from horilla.utils import timezone
from horilla.utils.decorators import (
    htmx_required,
    method_decorator,
    permission_required_or_denied,
)
from horilla.utils.translation import gettext as _
from horilla.views.generic import View
from horilla.web import HttpResponse, ScriptResponse

# Local imports
from ...models import HorillaMail, HorillaMailAttachment, HorillaMailConfiguration
from ...views.core.base import extract_inline_images_with_cid

logger = logging.getLogger(__name__)


@method_decorator(htmx_required, name="dispatch")
class HorillaMailtDeleteView(LoginRequiredMixin, HorillaSingleDeleteView):
    """
    Delete Horilla Mail view with post-delete redirection based on 'view' parameter
    """

    model = HorillaMail
    check_delete_permission = False

    def _can_delete_mail(self, request, pk):
        user = request.user
        if user.is_superuser or user.has_perm("mail.delete_horillamail"):
            return True
        try:
            mail = HorillaMail.objects.get(pk=pk)
            if mail.content_type and mail.object_id:
                model_class = apps.get_model(
                    mail.content_type.app_label, mail.content_type.model
                )
                related_obj = model_class.objects.get(pk=mail.object_id)
                return check_record_access(user, related_obj)
        except Exception:
            pass
        return False

    def dispatch(self, request, *args, **kwargs):
        """Require delete access on the mail or related record before proceeding."""
        pk = kwargs.get("pk")
        if not self._can_delete_mail(request, pk):
            return render(request, "403.html", status=403)
        return super().dispatch(request, *args, **kwargs)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.view_param = None

    def post(self, request, *args, **kwargs):
        self.from_param = request.GET.get("from")
        view_from_get = request.GET.get("view")
        if view_from_get:
            pk = kwargs.get("pk") or self.kwargs.get("pk")
            request.session[f"mail_delete_view_{pk}"] = view_from_get
            self.view_param = view_from_get
        else:
            pk = kwargs.get("pk") or self.kwargs.get("pk")
            self.view_param = request.session.get(f"mail_delete_view_{pk}")
        return super().post(request, *args, **kwargs)

    def get_post_delete_response(self):

        if getattr(self, "from_param", None) == "mail_history":
            messages.success(self.request, _("Mail deleted successfully."))
            return ScriptResponse(close=True, reload=True)

        view = getattr(self, "view_param", None)

        if view:
            pk = self.kwargs.get("pk")
            session_key = f"mail_delete_view_{pk}"
            if session_key in self.request.session:
                del self.request.session[session_key]

        sub_tab_map = {
            "sent": "sent",
            "draft": "draft",
            "scheduled": "scheduled",
        }
        sub_tab_id = sub_tab_map.get(view, "sent")

        return HttpResponse(
            f"<script>"
            f"localStorage.setItem('horilla_active_activity_tab', 'tab-email');"
            f"localStorage.setItem('horilla_active_activity_subtab', '{sub_tab_id}');"
            f"</script>"
        )


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied(
        [
            "mail.add_horillamail",
            "mail.add_own_horillamail",
        ]
    ),
    name="dispatch",
)
class ScheduleMailView(LoginRequiredMixin, View):
    """
    Schedule mail view - saves draft with scheduled send time
    """

    def _validate_schedule_datetime(self, scheduled_at):
        """Validate and parse scheduled datetime string."""
        if not scheduled_at:
            return None, {"schedule_datetime": _("Schedule time is required")}

        try:
            try:
                schedule_at_naive = datetime.strptime(scheduled_at, "%Y-%m-%dT%H:%M")
            except ValueError:
                schedule_at_naive = datetime.strptime(scheduled_at, "%Y-%m-%d %H:%M")

            user_tz = timezone.get_current_timezone()
            schedule_at = timezone.make_aware(schedule_at_naive, user_tz)

            if schedule_at <= timezone.now():
                return None, {
                    "schedule_datetime": _("Scheduled time must be in the future")
                }

            return schedule_at, {}
        except ValueError:
            return None, {"schedule_datetime": _("Invalid date/time format")}

    def _render_error_response(
        self,
        request,
        errors,
        model_name=None,
        object_id=None,
        pk=None,
        is_reschedule=False,
        scheduled_at="",
    ):
        """Render error response with form context."""
        non_field_errors = {k: v for k, v in errors.items() if k != "schedule_datetime"}
        context = {
            "model_name": model_name,
            "object_id": object_id,
            "pk": pk,
            "is_reschedule": is_reschedule,
            "errors": errors,
            "non_field_errors": non_field_errors,
            "scheduled_at": scheduled_at or "",
        }
        return render(request, "schedule_mail_form.html", context)

    def _handle_reschedule(self, request, pk, scheduled_at):
        """Handle rescheduling of an existing mail."""
        errors = {}

        if not scheduled_at:
            errors["schedule_datetime"] = _("Schedule time is required")
            return self._render_error_response(
                request, errors, pk=pk, is_reschedule=True, scheduled_at=scheduled_at
            )

        try:
            draft_mail = HorillaMail.objects.get(pk=pk)
        except HorillaMail.DoesNotExist:
            errors["non_field_error"] = _(
                "Scheduled mail not found or you don't have permission"
            )
            return self._render_error_response(
                request, errors, pk=pk, is_reschedule=True, scheduled_at=scheduled_at
            )

        if not request.user.has_perm("mail.add_horillamail"):
            if draft_mail.created_by != request.user:
                errors["non_field_error"] = _(
                    "You do not have permission to reschedule this mail."
                )
                return self._render_error_response(
                    request,
                    errors,
                    pk=pk,
                    is_reschedule=True,
                    scheduled_at=scheduled_at,
                )

        schedule_at, validation_errors = self._validate_schedule_datetime(scheduled_at)
        if validation_errors:
            return self._render_error_response(
                request,
                validation_errors,
                pk=pk,
                is_reschedule=True,
                scheduled_at=scheduled_at,
            )

        draft_mail.scheduled_at = schedule_at
        draft_mail.save(update_fields=["scheduled_at"])

        messages.success(
            request,
            _("Mail rescheduled successfully for ")
            + schedule_at.strftime("%Y-%m-%d %H:%M"),
        )
        return ScriptResponse(close=True, extra="$('#scheduled-email-tab').click();")

    def _validate_form_fields(
        self, to_email, from_mail_id, scheduled_at, message_content
    ):
        """Validate form fields and return errors dict."""
        errors = {}

        if not to_email:
            errors["to_email"] = _("To email is required")
        if not from_mail_id:
            errors["from_mail"] = _("From mail configuration is required")
        if not scheduled_at:
            errors["schedule_datetime"] = _("Schedule time is required")

        # XSS validation is handled at model level via clean() method

        if scheduled_at:
            _schedule_at, validation_errors = self._validate_schedule_datetime(
                scheduled_at
            )
            errors.update(validation_errors)

        return errors

    def _get_or_create_draft_mail(
        self, request, pk, content_type, object_id, from_mail_config, company
    ):
        """Get existing draft mail or create a new one."""
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

        if not draft_mail:
            draft_mail = HorillaMail.objects.create(
                content_type=content_type,
                object_id=object_id or 0,
                mail_status="scheduled",
                created_by=request.user,
                sender=from_mail_config,
                company=company,
            )

        return draft_mail

    def _save_mail_attachments(
        self, draft_mail, uploaded_files, inline_images, company
    ):
        """Save mail attachments and inline images."""
        if not draft_mail.pk:
            return

        for f in uploaded_files:
            attachment = HorillaMailAttachment(mail=draft_mail, file=f, company=company)
            attachment.save()

        for img_file, cid in inline_images:
            attachment = HorillaMailAttachment(
                mail=draft_mail,
                file=img_file,
                company=company,
                is_inline=True,
                content_id=cid,
            )
            attachment.save()

    def _handle_new_schedule(self, request):
        """Handle creation of a new scheduled mail."""
        errors = {}

        to_email = request.POST.get("to_email", "")
        cc_email = request.POST.get("cc_email", "")
        bcc_email = request.POST.get("bcc_email", "")
        subject = request.POST.get("subject", "")
        message_content = request.POST.get("message_content", "")
        from_mail_id = request.POST.get("from_mail")
        uploaded_files = request.FILES.getlist("attachments")
        scheduled_at = request.POST.get("schedule_datetime")

        model_name = request.GET.get("model_name")
        object_id = request.GET.get("object_id")
        pk = request.GET.get("pk")
        is_reschedule = False

        company = get_active_company(request)
        setattr(_thread_local, "from_mail_id", from_mail_id)

        errors = self._validate_form_fields(
            to_email, from_mail_id, scheduled_at, message_content
        )

        if errors:
            return self._render_error_response(
                request, errors, model_name, object_id, pk, is_reschedule, scheduled_at
            )

        try:
            from_mail_config = HorillaMailConfiguration.objects.get(id=from_mail_id)
        except HorillaMailConfiguration.DoesNotExist:
            errors["from_mail"] = _("Invalid mail configuration selected")
            return self._render_error_response(
                request, errors, model_name, object_id, pk, is_reschedule, scheduled_at
            )

        content_type = None
        if model_name and object_id:
            try:
                content_type = HorillaContentType.objects.get(model=model_name.lower())
            except HorillaContentType.DoesNotExist:
                errors["non_field_error"] = f"Invalid model name: {model_name}"
                return self._render_error_response(
                    request,
                    errors,
                    model_name,
                    object_id,
                    pk,
                    is_reschedule,
                    scheduled_at,
                )

        if (
            content_type
            and object_id
            and not request.user.has_perm("mail.add_horillamail")
        ):
            try:
                model_class = apps.get_model(content_type.app_label, content_type.model)
                related_obj = model_class.objects.get(pk=object_id)
                owner_fields = getattr(model_class, "OWNER_FIELDS", [])
                if not any(
                    getattr(related_obj, f, None) == request.user for f in owner_fields
                ):
                    errors["non_field_error"] = _(
                        "You do not have permission to send mail for this record."
                    )
                    return self._render_error_response(
                        request,
                        errors,
                        model_name,
                        object_id,
                        pk,
                        is_reschedule,
                        scheduled_at,
                    )
            except Exception:
                errors["non_field_error"] = _(
                    "You do not have permission to send mail for this record."
                )
                return self._render_error_response(
                    request,
                    errors,
                    model_name,
                    object_id,
                    pk,
                    is_reschedule,
                    scheduled_at,
                )

        schedule_at, _unused = self._validate_schedule_datetime(scheduled_at)

        draft_mail = self._get_or_create_draft_mail(
            request, pk, content_type, object_id, from_mail_config, company
        )

        request_info = {
            "host": request.get_host(),
            "scheme": request.scheme,
        }

        cleaned_message_content, inline_images = extract_inline_images_with_cid(
            message_content
        )

        draft_mail.sender = from_mail_config
        draft_mail.to = to_email
        draft_mail.cc = cc_email if cc_email else None
        draft_mail.bcc = bcc_email if bcc_email else None
        draft_mail.subject = subject if subject else None
        draft_mail.body = cleaned_message_content if cleaned_message_content else None
        draft_mail.mail_status = "scheduled"
        draft_mail.scheduled_at = schedule_at
        if draft_mail.additional_info is None:
            draft_mail.additional_info = {}
        draft_mail.additional_info["request_info"] = request_info
        draft_mail.save()

        self._save_mail_attachments(draft_mail, uploaded_files, inline_images, company)

        messages.success(
            request,
            _("Mail scheduled successfully for ")
            + schedule_at.strftime("%Y-%m-%d %H:%M"),
        )
        return ScriptResponse(
            extra="closehorillaModal();$('#scheduled-email-tab').click();", close=True
        )

    def post(self, request, *args, **kwargs):
        """Handle scheduling mail - new or reschedule existing."""
        pk = kwargs.get("pk") or request.GET.get("pk")
        scheduled_at = request.POST.get("schedule_datetime")
        is_reschedule = bool(kwargs.get("pk"))

        if is_reschedule:
            return self._handle_reschedule(request, pk, scheduled_at)

        try:
            return self._handle_new_schedule(request)
        except Exception as e:
            import traceback

            logger.error(traceback.format_exc())
            model_name = request.GET.get("model_name")
            object_id = request.GET.get("object_id")
            pk = request.GET.get("pk")
            is_reschedule = False
            scheduled_at = request.POST.get("schedule_datetime", "")
            errors = {"non_field_error": _("Error scheduling mail: ") + str(e)}
            return self._render_error_response(
                request, errors, model_name, object_id, pk, is_reschedule, scheduled_at
            )


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied(
        [
            "mail.add_horillamail",
            "mail.add_own_horillamail",
        ]
    ),
    name="dispatch",
)
class ScheduleMailModallView(LoginRequiredMixin, View):
    """
    Open the schedule modal
    """

    def get(self, request, *args, **kwargs):
        """
        Render the schedule mail modal form"""
        model_name = request.GET.get("model_name")
        object_id = request.GET.get("object_id")
        pk = request.GET.get("pk") or kwargs.get("pk")
        is_reschedule = bool(kwargs.get("pk"))
        scheduled_at_formatted = ""

        if (
            not request.user.has_perm("mail.add_horillamail")
            and model_name
            and object_id
        ):
            try:
                ct = HorillaContentType.objects.get(model=model_name.lower())
                model_class = apps.get_model(ct.app_label, ct.model)
                related_obj = model_class.objects.get(pk=object_id)
                owner_fields = getattr(model_class, "OWNER_FIELDS", [])
                if not any(
                    getattr(related_obj, f, None) == request.user for f in owner_fields
                ):
                    return render(request, "403.html", status=403)
            except Exception:
                return render(request, "403.html", status=403)

        if pk:
            mail = get_object_or_404(HorillaMail, pk=pk)
            if mail.scheduled_at:
                user_tz = timezone.get_current_timezone()
                scheduled_at_local = mail.scheduled_at.astimezone(user_tz)
                scheduled_at_formatted = scheduled_at_local.strftime("%Y-%m-%dT%H:%M")

        context = {
            "model_name": model_name,
            "object_id": object_id,
            "pk": pk,
            "is_reschedule": is_reschedule,
            "scheduled_at": scheduled_at_formatted,
        }

        return render(request, "schedule_mail_form.html", context)
