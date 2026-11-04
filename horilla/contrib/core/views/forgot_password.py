"""
Module providing forgot password and password reset functionality for Horilla users.
Includes HTMX support for dynamic interactions.
"""

# Standard library imports
import logging

# Third-party imports (Django)
from django.conf import settings
from django.contrib import messages
from django.contrib.auth import update_session_auth_hash
from django.contrib.auth.password_validation import validate_password
from django.contrib.auth.tokens import default_token_generator
from django.core.mail import EmailMessage
from django.template.loader import render_to_string
from django.utils.encoding import force_bytes, force_str
from django.utils.http import urlsafe_base64_decode, urlsafe_base64_encode

from horilla.auth.models import User
from horilla.contrib.mail.models import HorillaMailConfiguration
from horilla.core.exceptions import ValidationError

# First party imports (Horilla)
from horilla.db.models import Q
from horilla.shortcuts import redirect, render
from horilla.utils.branding import load_branding
from horilla.utils.html import strip_tags
from horilla.utils.translation import gettext_lazy as _
from horilla.utils.urls import build_absolute_url
from horilla.views.generic import View
from horilla.web import HttpResponse

# Local imports
from ..models import Company

logger = logging.getLogger(__name__)


class ForgotPasswordView(View):
    """
    View to handle the forgot password workflow.

    GET: Display the forgot password form.
    POST: Process the form submission and send a password reset email.
    """

    template_name = "forgot_password/forgot_password.html"
    success_template = "forgot_password/forgot_password_success_partial.html"

    def get(self, request):
        """Display the forgot password form"""
        return render(request, self.template_name)

    def post(self, request):
        """Handle password reset email submission"""
        email_or_username = request.POST.get("email")

        try:
            user = User.objects.get(
                Q(email=email_or_username) | Q(username=email_or_username)
            )

            token = default_token_generator.make_token(user)
            uid = urlsafe_base64_encode(force_bytes(user.pk))

            reset_link = build_absolute_url(
                f"/reset-password/{uid}/{token}/", request=request
            )

            primary_config = HorillaMailConfiguration.objects.filter(
                is_primary=True, company=user.company
            ).first()

            if not primary_config:
                hq_company = Company.objects.filter(hq=True).first()
                if hq_company:
                    primary_config = HorillaMailConfiguration.objects.filter(
                        is_primary=True, company=hq_company
                    ).first()

            product_name = load_branding()["TITLE"]
            context = {
                "user": user,
                "reset_link": reset_link,
                "site_name": getattr(settings, "SITE_NAME", product_name),
            }

            html_message = render_to_string(
                "forgot_password/password_reset_email.html", context
            )
            plain_message = strip_tags(html_message)

            email = EmailMessage(
                subject=f"Password Reset Request - {product_name}",
                body=plain_message,
                from_email=(
                    primary_config.from_email
                    if primary_config
                    else settings.DEFAULT_FROM_EMAIL
                ),
                to=[user.email],
            )

            email.content_subtype = "html"
            email.body = html_message

            email.send(fail_silently=False)

        except User.DoesNotExist:
            # Intentionally silent — do not reveal whether account exists
            logger.info(
                "Password reset requested for unknown account: %s", email_or_username
            )

        except Exception:
            logger.exception("Password reset email failed for: %s", email_or_username)

        # Always return the same success response regardless of account existence
        return render(request, self.success_template)


class PasswordResetConfirmView(View):
    """
    View to handle the password reset confirmation workflow.

    GET: Display the reset password form if the token is valid.
    POST: Process the form submission to reset the user's password.
    """

    template_name = "forgot_password/password_reset_confirm.html"
    success_template = "forgot_password/password_reset_success_partial.html"

    def get(self, request, uidb64, token):
        """Display the password reset form"""
        try:
            uid = force_str(urlsafe_base64_decode(uidb64))
            user = User.objects.get(pk=uid)

            if default_token_generator.check_token(user, token):
                context = {
                    "validlink": True,
                    "uidb64": uidb64,
                    "token": token,
                }
            else:
                context = {"validlink": False}

        except Exception as e:
            context = {"validlink": False, "error": str(e)}

        return render(request, self.template_name, context)

    def post(self, request, uidb64, token):
        """Handle password reset via HTMX"""
        try:
            uid = force_str(urlsafe_base64_decode(uidb64))
            user = User.objects.get(pk=uid)

            if not default_token_generator.check_token(user, token):
                messages.error(
                    request, "Password reset link is invalid or has expired."
                )
                context = {"validlink": False}
                return render(request, self.template_name, context)

            new_password = request.POST.get("new_password")
            confirm_password = request.POST.get("confirm_password")

            if not new_password or not confirm_password:
                messages.error(request, _("Please fill in all password fields."))
            elif new_password != confirm_password:
                messages.error(request, _("Passwords do not match."))
            else:
                try:
                    validate_password(new_password, user=user)
                except ValidationError as e:
                    for message in e.messages:
                        messages.error(request, message)
                else:
                    user.set_password(new_password)
                    user.save()
                    update_session_auth_hash(request, user)
                    messages.success(
                        request, "Your password has been reset successfully."
                    )

                    if request.headers.get("HX-Request") == "true":
                        response = HttpResponse()
                        response["HX-Redirect"] = "/login/"
                        response["HX-Push-Url"] = "/login/"
                        return response

                    return redirect("core:login")

            context = {
                "validlink": True,
                "uidb64": uidb64,
                "token": token,
                "new_password": new_password,
                "confirm_password": confirm_password,
            }
            return render(request, self.template_name, context)

        except (TypeError, ValueError, OverflowError, User.DoesNotExist):
            messages.error(request, _("Invalid password reset link."))
            context = {"validlink": False}
            return render(request, self.template_name, context)
