"""Recipient and field selection views (add/remove email, suggestions, field selection)."""

# Standard library imports
import logging

from horilla.apps import apps

# First party imports (Horilla)
from horilla.auth.mixins import LoginRequiredMixin
from horilla.shortcuts import render
from horilla.utils.decorators import (
    htmx_required,
    method_decorator,
    permission_required_or_denied,
)
from horilla.views.generic import View

# Local imports
from ...models import HorillaMail

logger = logging.getLogger(__name__)


@method_decorator(
    permission_required_or_denied(
        [
            "mail.change_horillamail",
            "mail.change_own_horillamail",
        ]
    ),
    name="dispatch",
)
class AddEmailView(LoginRequiredMixin, View):
    """
    View to add email as a pill and clear search input
    """

    def post(self, request, *args, **kwargs):
        """
        Add email to the pill list
        """
        email = request.POST.get("email", "").strip()
        field_type = request.POST.get("field_type", "to")
        current_email_list = request.POST.get(f"{field_type}_email_list", "")

        if current_email_list:
            email_list = [e.strip() for e in current_email_list.split(",") if e.strip()]
        else:
            email_list = []

        if email and email not in email_list:
            email_list.append(email)

        email_string = ", ".join(email_list)

        context = {
            "email_list": email_list,
            "email_string": email_string,
            "field_type": field_type,
            "current_search": "",
        }

        return render(request, "email_pills_field.html", context)


@method_decorator(
    permission_required_or_denied(
        [
            "mail.change_horillamail",
            "mail.change_own_horillamail",
        ]
    ),
    name="dispatch",
)
class RemoveEmailView(LoginRequiredMixin, View):
    """
    View to remove specific email pill
    """

    def post(self, request, *args, **kwargs):
        """
        Remove email from the pill list
        """
        email_to_remove = request.POST.get("email_to_remove", "").strip()
        field_type = request.POST.get("field_type", "to")
        current_email_list = request.POST.get(f"{field_type}_email_list", "")

        if current_email_list:
            email_list = [e.strip() for e in current_email_list.split(",") if e.strip()]
        else:
            email_list = []

        if email_to_remove in email_list:
            email_list.remove(email_to_remove)

        email_string = ", ".join(email_list)

        context = {
            "email_list": email_list,
            "email_string": email_string,
            "field_type": field_type,
            "current_search": "",
        }

        return render(request, "email_pills_field.html", context)


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
class EmailSuggestionView(LoginRequiredMixin, View):
    """
    View to get email suggestions (updated to work with pills)
    """

    def get_all_emails_from_models(self):
        """
        Extract all email addresses from all models in the project
        """
        all_emails = set()

        for model in apps.get_models():
            model_name = model._meta.model_name.lower()
            if model_name in [
                "session",
                "contenttype",
                "permission",
                "group",
                "logentry",
            ]:
                continue

            for field in model._meta.get_fields():
                if (
                    "email" in field.name.lower()
                    or field.__class__.__name__ == "EmailField"
                ):
                    try:
                        values = model.objects.values_list(
                            field.name, flat=True
                        ).distinct()
                        for value in values:
                            if value and "@" in str(value):
                                self._extract_emails_from_string(str(value), all_emails)
                    except Exception:
                        continue

        try:
            for field_name in ["to", "cc", "bcc"]:
                try:
                    email_values = HorillaMail.objects.values_list(
                        field_name, flat=True
                    ).distinct()
                    for email_string in email_values:
                        if email_string:
                            self._extract_emails_from_string(email_string, all_emails)
                except Exception:
                    continue

        except ImportError:
            pass

        valid_emails = []
        for email in all_emails:
            if self._is_valid_email(email):
                valid_emails.append(email.lower())

        return sorted(list(set(valid_emails)))

    def _extract_emails_from_string(self, email_string, email_set):
        """
        Extract individual emails from a string that might contain multiple emails
        """
        if "," in email_string:
            emails = [email.strip() for email in email_string.split(",")]
            email_set.update(emails)
        elif ";" in email_string:
            emails = [email.strip() for email in email_string.split(";")]
            email_set.update(emails)
        else:
            email_set.add(email_string.strip())

    def _is_valid_email(self, email):
        """
        Basic email validation
        """
        if not email or len(email) < 5:
            return False
        if "@" not in email:
            return False
        parts = email.split("@")
        if len(parts) != 2:
            return False
        if "." not in parts[1]:
            return False
        return True

    def get(self, request, *args, **kwargs):
        """
        Return email suggestions based on search query
        """
        field_type = request.GET.get("field", "to")
        current_input = request.GET.get(f"{field_type}_email_input", "").strip()
        current_email_list = request.GET.get(f"{field_type}_email_list", "")

        existing_emails = []
        if current_email_list:
            existing_emails = [
                e.strip().lower() for e in current_email_list.split(",") if e.strip()
            ]

        all_emails = self.get_all_emails_from_models()

        available_emails = [
            email for email in all_emails if email.lower() not in existing_emails
        ]

        if current_input:
            search_lower = current_input.lower()
            filtered_emails = [
                email for email in available_emails if search_lower in email.lower()
            ]
            exact_matches = [e for e in filtered_emails if e.lower() == search_lower]
            starts_with = [
                e
                for e in filtered_emails
                if e.lower().startswith(search_lower) and e not in exact_matches
            ]
            contains = [
                e
                for e in filtered_emails
                if search_lower in e.lower()
                and e not in exact_matches
                and e not in starts_with
            ]

            filtered_emails = exact_matches + starts_with + contains
        else:
            filtered_emails = available_emails[:10]

        filtered_emails = filtered_emails[:15]

        context = {
            "emails": filtered_emails,
            "field_type": field_type,
            "query": current_input,
        }

        return render(request, "email_suggestions.html", context)
