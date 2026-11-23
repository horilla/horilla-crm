"""Mail form view - send form and draft creation."""

# Third-party imports (Django)
# Standard library imports
import logging

from django.contrib import messages

from horilla.apps import apps

# First party imports (Horilla)
from horilla.auth.mixins import LoginRequiredMixin
from horilla.contrib.core.models import HorillaContentType
from horilla.contrib.generics.views.details import check_record_access
from horilla.contrib.utils.middlewares import _thread_local, get_active_company
from horilla.core.exceptions import ValidationError
from horilla.shortcuts import render
from horilla.utils.decorators import htmx_required, method_decorator
from horilla.utils.translation import gettext as _
from horilla.views.generic import TemplateView
from horilla.web import HttpResponse, HxTriggerResponse, JsonResponse, ScriptResponse

# Local imports
from ...models import HorillaMail, HorillaMailAttachment, HorillaMailConfiguration
from ...services import HorillaMailManager
from ...views.core.base import extract_inline_images_with_cid, parse_email_pills_context

logger = logging.getLogger(__name__)


@method_decorator(htmx_required, name="dispatch")
class HorillaMailFormView(LoginRequiredMixin, TemplateView):
    """
    Send mail form view - automatically creates a draft mail
    """

    template_name = "mail_form.html"

    def _has_mail_access(self, request):
        """Return True if user can access the parent record."""
        user = request.user
        if user.is_superuser:
            return True
        # Try via model_name + object_id in GET params
        model_name = request.GET.get("model_name")
        object_id = request.GET.get("object_id")
        if model_name and object_id:
            try:
                ct = HorillaContentType.objects.get(model=model_name.lower())
                model_class = apps.get_model(ct.app_label, ct.model)
                related_obj = model_class.objects.get(pk=object_id)
                return check_record_access(user, related_obj)
            except Exception:
                pass
        # Fallback: draft pk in URL kwargs — look up parent via draft's content_type
        pk = self.kwargs.get("pk") or request.GET.get("pk")
        if pk:
            try:
                draft = HorillaMail.objects.get(pk=pk)
                if draft.content_type and draft.object_id:
                    model_class = apps.get_model(
                        draft.content_type.app_label, draft.content_type.model
                    )
                    related_obj = model_class.objects.get(pk=draft.object_id)
                    return check_record_access(user, related_obj)
            except Exception:
                pass
        return False

    def dispatch(self, request, *args, **kwargs):
        """Require access to the related record before opening the mail form."""
        if not self._has_mail_access(request):
            return render(request, "403.html", status=403)
        return super().dispatch(request, *args, **kwargs)

    def get(self, request, *args, **kwargs):
        """Render mail form or config-required message; create draft when pk/cancel provided."""
        company = get_active_company(request)
        outgoing_mail_exists = HorillaMailConfiguration.objects.filter(
            mail_channel="outgoing", company=company, is_active=True
        ).exists()

        if not outgoing_mail_exists:
            return render(
                request,
                "mail_config_required.html",
                {
                    "message": _(
                        "Cannot send email. Outgoing mail must be configured first."
                    ),
                },
            )
        pk = kwargs.get("pk") or request.GET.get("pk")
        cancel = self.request.GET.get("cancel") == "true"
        if pk:
            try:
                draft_mail = HorillaMail.objects.get(pk=pk)
                if cancel:
                    draft_mail.mail_status = "draft"
                    draft_mail.save()
            except Exception as e:
                messages.error(self.request, e)
                return ScriptResponse(reload=True, close=True)

        return super().get(request, *args, **kwargs)

    def _extract_form_data(self, request):
        """Extract form data from request."""
        pk_value = request.GET.get("pk") or request.POST.get("pk")
        # Normalize pk: convert string 'None', 'null', or empty to None
        if pk_value in (None, "", "None", "null"):
            pk_value = None

        # Try to get model_name and object_id from both GET and POST
        model_name = request.GET.get("model_name") or request.POST.get("model_name")
        object_id = request.GET.get("object_id") or request.POST.get("object_id")

        return {
            "to_email": request.POST.get("to_email", ""),
            "cc_email": request.POST.get("cc_email", ""),
            "bcc_email": request.POST.get("bcc_email", ""),
            "subject": request.POST.get("subject", ""),
            "message_content": request.POST.get("message_content", ""),
            "from_mail_id": request.POST.get("from_mail"),
            "uploaded_files": request.FILES.getlist("attachments"),
            "model_name": model_name,
            "object_id": object_id,
            "pk": pk_value,
            "company": get_active_company(request),
        }

    def _validate_required_fields(self, form_data):
        """Validate required fields and return validation errors dict."""
        validation_errors = {}
        if not form_data["to_email"]:
            validation_errors["to_email"] = _("To email is required")
        if not form_data["from_mail_id"]:
            validation_errors["from_mail"] = _("From mail configuration is required")
        return validation_errors

    def _build_validation_error_response(self, form_data, validation_errors, kwargs):
        """Build and return validation error response."""
        context = self.get_context_data(**kwargs)
        context["validation_errors"] = validation_errors
        context["subject"] = form_data["subject"]
        context["message_content"] = form_data["message_content"]
        context["form_data"] = {
            "to_email": form_data["to_email"],
            "cc_email": form_data["cc_email"],
            "bcc_email": form_data["bcc_email"],
            "subject": form_data["subject"],
            "message_content": form_data["message_content"],
            "from_mail_id": form_data["from_mail_id"],
        }
        context["to_pills"] = parse_email_pills_context(
            form_data["to_email"] or "", "to"
        )
        context["cc_pills"] = parse_email_pills_context(
            form_data["cc_email"] or "", "cc"
        )
        context["bcc_pills"] = parse_email_pills_context(
            form_data["bcc_email"] or "", "bcc"
        )
        response = self.render_to_response(context)
        response["HX-Select"] = "#send-mail-container"
        return response

    def _get_content_type(self, model_name, object_id, request):
        """Get HorillaContentType for model_name if provided."""
        if not (model_name and object_id):
            return None
        try:
            return HorillaContentType.objects.get(model=model_name.lower())
        except HorillaContentType.DoesNotExist:
            messages.error(request, f"Invalid model name: {model_name}")
            return None

    def _get_or_create_draft_mail(
        self, form_data, from_mail_config, content_type, request
    ):
        """Get existing draft mail or create a new one."""
        draft_mail = None
        if content_type and form_data["object_id"]:
            try:
                draft_mail = HorillaMail.objects.filter(
                    pk=form_data["pk"],
                    content_type=content_type,
                    object_id=form_data["object_id"],
                    mail_status="draft",
                    created_by=request.user,
                ).first()
            except Exception as e:
                logger.error("Error finding draft: %s", e)

        if not draft_mail:
            draft_mail = HorillaMail.objects.create(
                content_type=content_type,
                object_id=form_data["object_id"] or 0,
                mail_status="draft",
                created_by=request.user,
                sender=from_mail_config,
                company=form_data["company"],
            )
        return draft_mail

    def _update_draft_mail(self, draft_mail, form_data, from_mail_config):
        """Update draft mail with form data."""
        cleaned_message_content, inline_images = extract_inline_images_with_cid(
            form_data["message_content"]
        )
        draft_mail.sender = from_mail_config
        draft_mail.to = form_data["to_email"]
        draft_mail.cc = form_data["cc_email"] if form_data["cc_email"] else None
        draft_mail.bcc = form_data["bcc_email"] if form_data["bcc_email"] else None
        draft_mail.subject = form_data["subject"] if form_data["subject"] else None
        draft_mail.body = cleaned_message_content if cleaned_message_content else None
        draft_mail.save()
        return inline_images

    def _save_attachments(self, draft_mail, form_data, inline_images):
        """Save file attachments and inline images."""
        if not draft_mail.pk:
            return
        for uploaded_file in form_data["uploaded_files"]:
            attachment = HorillaMailAttachment(
                mail=draft_mail, file=uploaded_file, company=form_data["company"]
            )
            attachment.save()
        for img_file, cid in inline_images:
            attachment = HorillaMailAttachment(
                mail=draft_mail,
                file=img_file,
                company=form_data["company"],
                is_inline=True,
                content_id=cid,
            )
            attachment.save()

    def _build_template_context(self, request, content_type, object_id):
        """Build template context for email sending."""
        template_context = {
            "user": request.user,
            "request": request,
        }
        if get_active_company(request):
            template_context["active_company"] = (get_active_company(request),)
        if content_type and object_id:
            try:
                model_class = apps.get_model(
                    app_label=content_type.app_label, model_name=content_type.model
                )
                related_object = model_class.objects.get(pk=object_id)
                template_context["instance"] = related_object
            except Exception as e:
                logger.error("Error getting related object: %s", e)
        return template_context

    def post(self, request, *args, **kwargs):
        """
        Handle the submission of the mail form.
        """
        try:
            form_data = self._extract_form_data(request)
            setattr(_thread_local, "from_mail_id", form_data["from_mail_id"])

            validation_errors = self._validate_required_fields(form_data)
            if validation_errors:
                return self._build_validation_error_response(
                    form_data, validation_errors, kwargs
                )

            # XSS validation is now handled at model level via clean() method

            try:
                from_mail_config = HorillaMailConfiguration.objects.get(
                    id=form_data["from_mail_id"]
                )
            except HorillaMailConfiguration.DoesNotExist:
                return JsonResponse(
                    {"success": False, "message": "Invalid mail configuration selected"}
                )

            # If we have a pk, get the draft_mail first to extract model_name and object_id
            draft_mail = None
            content_type = None
            pk_value = form_data.get("pk")
            # pk_value is already normalized in _extract_form_data, just check if it exists
            if pk_value:
                try:
                    # Ensure it's an integer
                    pk_value = int(pk_value)
                    draft_mail = HorillaMail.objects.get(
                        pk=pk_value,
                        mail_status="draft",
                        created_by=request.user,
                    )
                    # Use content_type from existing draft_mail
                    content_type = draft_mail.content_type
                    # Extract model_name and object_id from existing draft_mail
                    if draft_mail.content_type:
                        form_data["model_name"] = draft_mail.content_type.model
                    if draft_mail.object_id:
                        form_data["object_id"] = draft_mail.object_id
                except (HorillaMail.DoesNotExist, ValueError):
                    pass

            if not content_type:
                if form_data.get("model_name") and form_data.get("object_id"):
                    content_type = self._get_content_type(
                        form_data["model_name"], form_data["object_id"], request
                    )
                    if not content_type:
                        # Error already shown in _get_content_type, just return
                        return HxTriggerResponse(extra="closehorillaModal();")
                else:
                    if draft_mail and draft_mail.content_type:
                        content_type = draft_mail.content_type
                        form_data["model_name"] = draft_mail.content_type.model
                        form_data["object_id"] = draft_mail.object_id
                    elif not content_type and (
                        form_data.get("model_name") or form_data.get("object_id")
                    ):
                        messages.error(
                            request,
                            _(
                                "Both model_name and object_id are required to send mail related to an object."
                            ),
                        )
                        return HxTriggerResponse(extra="closehorillaModal();")

            if (
                not request.user.has_perm("mail.add_horillamail")
                and content_type
                and form_data.get("object_id")
            ):
                try:
                    model_class = apps.get_model(
                        content_type.app_label, content_type.model
                    )
                    related_obj = model_class.objects.get(pk=form_data["object_id"])
                    if not check_record_access(request.user, related_obj):
                        return render(request, "403.html", status=403)
                except Exception:
                    return render(request, "403.html", status=403)

            # For sending mail, only use existing draft if pk exists, don't create new draft
            # Create a mail object for sending (will be saved only if successfully sent)
            if not draft_mail:
                if not content_type:
                    messages.error(
                        request,
                        _(
                            "Cannot send mail: model information is missing. Please try again from the opportunity page."
                        ),
                    )
                    return HxTriggerResponse(extra="closehorillaModal();")
                # Create mail object for sending (not saved yet, will be saved only if sent successfully)
                cleaned_message_content, inline_images = extract_inline_images_with_cid(
                    form_data["message_content"]
                )
                draft_mail = HorillaMail(
                    content_type=content_type,
                    object_id=form_data["object_id"] or 0,
                    mail_status="draft",  # Will be changed to "sent" if successful
                    created_by=request.user,
                    sender=from_mail_config,
                    company=form_data["company"],
                    to=form_data["to_email"],
                    cc=form_data["cc_email"] if form_data["cc_email"] else None,
                    bcc=form_data["bcc_email"] if form_data["bcc_email"] else None,
                    subject=form_data["subject"] if form_data["subject"] else None,
                    body=cleaned_message_content if cleaned_message_content else None,
                )
            else:
                # Update existing draft with form data
                inline_images = self._update_draft_mail(
                    draft_mail, form_data, from_mail_config
                )

            # Validate before sending (but don't save as draft yet)
            try:
                draft_mail.full_clean()
            except ValidationError as e:
                validation_errors = {}
                if hasattr(e, "error_dict"):
                    for field, errors in e.error_dict.items():
                        if errors:
                            validation_errors[field] = " ".join(
                                [str(err) for err in errors]
                            )
                        else:
                            validation_errors[field] = str(e)
                elif hasattr(e, "error_list"):
                    validation_errors["non_field_errors"] = " ".join(
                        [str(err) for err in e.error_list]
                    )
                else:
                    validation_errors["non_field_errors"] = str(e)

                return self._build_validation_error_response(
                    form_data, validation_errors, kwargs
                )

            # Save mail object (needed for attachments and sending)
            # If it's a new mail, save it first to get pk for attachments
            if not draft_mail.pk:
                draft_mail.save()

            self._save_attachments(draft_mail, form_data, inline_images)

            object_id = (
                draft_mail.object_id
                if draft_mail and draft_mail.object_id
                else form_data["object_id"]
            )
            template_context = self._build_template_context(
                request, content_type, object_id
            )

            # Send mail - this will update status to "sent" or "failed" and save
            HorillaMailManager.send_mail(draft_mail, template_context)
            draft_mail.refresh_from_db()

            if draft_mail.mail_status in ("sent", "delivered"):
                messages.success(request, _("Mail sent successfully"))
            elif draft_mail.mail_status == "bounced":
                messages.error(
                    request, _("Mail bounced: ") + draft_mail.mail_status_message
                )
            else:
                # If sending failed, delete the draft that was created for sending
                if not form_data.get(
                    "pk"
                ):  # Only delete if it was a new mail (not existing draft)
                    try:
                        draft_mail.delete()
                    except Exception:
                        pass
                messages.error(
                    request, _("Failed to send mail: ") + draft_mail.mail_status_message
                )
            return HttpResponse(
                "<script>closehorillaModal();htmx.trigger('#sent-email-tab','click');</script>"
            )

        except Exception as e:
            import traceback

            logger.error(traceback.format_exc())

            messages.error(request, _("Error sending mail: ") + str(e))
            return HxTriggerResponse(extra="closehorillaModal();")

    def get_context_data(self, **kwargs):
        """Build context with draft mail, mail configs, and model/object info for the mail form."""
        context = super().get_context_data(**kwargs)
        draft_mail = None

        model_name = self.request.GET.get("model_name")
        object_id = self.request.GET.get("object_id")
        pk = kwargs.get("pk")
        primary_mail_config = HorillaMailConfiguration.objects.filter(
            is_primary=True
        ).first()
        if not primary_mail_config:
            primary_mail_config = HorillaMailConfiguration.objects.first()
        all_mail_configs = HorillaMailConfiguration.objects.filter(
            mail_channel="outgoing"
        )

        if pk:
            draft_mail = HorillaMail.objects.filter(pk=pk).first()
            # If we have an existing draft_mail, try to get the related object
            if draft_mail and draft_mail.content_type and draft_mail.object_id:
                try:
                    model_class = apps.get_model(
                        app_label=draft_mail.content_type.app_label,
                        model_name=draft_mail.content_type.model,
                    )
                    related_object = model_class.objects.get(pk=draft_mail.object_id)
                    context["related_object"] = related_object
                except Exception as e:
                    logger.error("Error getting related object from draft_mail: %s", e)
                    context["related_object"] = None
            else:
                context["related_object"] = None

        else:
            if model_name and object_id:
                try:
                    content_type = HorillaContentType.objects.get(
                        model=model_name.lower()
                    )

                    company = get_active_company(self.request)

                    try:
                        draft_mail = HorillaMail.objects.create(
                            content_type=content_type,
                            created_by=self.request.user,
                            object_id=object_id,
                            mail_status="draft",
                            sender=primary_mail_config,
                            company=company,
                        )
                        created = True

                        if created:
                            try:
                                model_class = apps.get_model(
                                    app_label=content_type.app_label,
                                    model_name=content_type.model,
                                )
                                related_object = model_class.objects.get(pk=object_id)

                                # Try to find an email field in the related object
                                email_value = None
                                for field in related_object._meta.get_fields():
                                    if (
                                        "email" in field.name.lower()
                                        or field.__class__.__name__ == "EmailField"
                                    ):
                                        email_value = getattr(
                                            related_object, field.name, None
                                        )
                                        if email_value:
                                            break

                                # If we found an email, set it in the draft
                                if email_value:
                                    draft_mail.to = email_value
                                    draft_mail.save()

                            except Exception as e:
                                logger.error(
                                    "Error setting related object email: %s", e
                                )

                    except Exception as e:
                        logger.error(str(e))

                    try:
                        model_class = apps.get_model(
                            app_label=content_type.app_label,
                            model_name=content_type.model,
                        )
                        related_object = model_class.objects.get(pk=object_id)
                        context["related_object"] = related_object
                    except Exception as e:
                        context["related_object"] = None

                except HorillaContentType.DoesNotExist:
                    pass
                except Exception as e:
                    pass
        existing_attachments = draft_mail.attachments.all() if draft_mail else []
        context["existing_attachments"] = existing_attachments
        context["message_content"] = (
            draft_mail.body if draft_mail and draft_mail.body else ""
        )
        context["subject"] = (
            draft_mail.subject if draft_mail and draft_mail.subject else ""
        )

        # Get model_name: prefer from draft_mail.content_type, fallback to GET param
        context_model_name = None
        if draft_mail and draft_mail.content_type:
            context_model_name = draft_mail.content_type.model.capitalize()
        elif model_name:
            # Use the model_name from GET params if draft_mail doesn't have it
            context_model_name = model_name.capitalize()

        context["model_name"] = context_model_name
        context["object_id"] = (
            draft_mail.object_id if draft_mail and draft_mail.object_id else object_id
        )
        context["pk"] = draft_mail.pk if draft_mail else None
        context["draft_mail"] = draft_mail
        context["primary_mail_config"] = primary_mail_config
        context["all_mail_configs"] = all_mail_configs
        context["to_pills"] = parse_email_pills_context(
            draft_mail.to if draft_mail else "", "to"
        )
        context["cc_pills"] = parse_email_pills_context(
            draft_mail.cc if draft_mail else "", "cc"
        )
        context["bcc_pills"] = parse_email_pills_context(
            draft_mail.bcc if draft_mail else "", "bcc"
        )
        return context
