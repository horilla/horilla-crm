"""Web-to-lead form builder and public form views."""

# Standard library imports
import json
from datetime import timedelta
from functools import cached_property
from urllib.parse import urlparse

# Third-party imports (Django)
from django import forms
from django.conf import settings
from django.core.cache import cache
from django.template.loader import render_to_string
from django.utils.safestring import mark_safe
from django.views.decorators.clickjacking import xframe_options_exempt
from django.views.decorators.csrf import csrf_exempt
from django.views.generic import CreateView

# First party imports (Horilla)
from horilla.auth.mixins import LoginRequiredMixin
from horilla.auth.models import User
from horilla.contrib.generics.views import HorillaNavView
from horilla.core.exceptions import FieldDoesNotExist
from horilla.db import transaction
from horilla.db.models import QuerySet
from horilla.extension.forms.resolve import resolve_form_class
from horilla.shortcuts import render
from horilla.urls import reverse, reverse_lazy
from horilla.utils import timezone, translation
from horilla.utils.decorators import (
    htmx_required,
    method_decorator,
    permission_required_or_denied,
)
from horilla.utils.html import js_json
from horilla.utils.translation import gettext_lazy as _
from horilla.utils.urls import build_absolute_url
from horilla.views.generic import FormView, TemplateView, View
from horilla.web import HttpNotFound, HttpResponse, RedirectResponse

# Local imports
from horilla_crm.leads.forms import WebToLeadForm
from horilla_crm.leads.models import Lead, LeadCaptureForm, LeadStatus


def build_public_form_url(request, form_id):
    """Build the absolute public-facing URL for a lead capture form."""
    path = reverse("leads:public_lead_form", kwargs={"form_id": form_id})
    return build_absolute_url(path, request=request)


def _public_form_rate_limited(request, form_id):
    """Count a submission per form and client IP; True once over the limit.

    Configurable with settings.WEB_TO_LEAD_RATE_LIMIT = (max_submissions, seconds).
    """
    limit, window = getattr(settings, "WEB_TO_LEAD_RATE_LIMIT", (20, 3600))
    if not limit:
        return False
    key = f"web_to_lead:{form_id}:{request.META.get('REMOTE_ADDR', '')}"
    cache.add(key, 0, window)
    try:
        return cache.incr(key) > limit
    except ValueError:
        return False


def parse_selected_fields(raw):
    """Return the stored field-name list, or [] if missing or invalid JSON."""
    if raw is None:
        return []
    if isinstance(raw, list):
        return raw
    text = str(raw).strip()
    if not text:
        return []
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return []
    return data if isinstance(data, list) else []


def find_recent_duplicate_lead(form_config, cleaned_data):
    """Return a lead created from this form moments ago with identical data, if any.

    Guards against repeated clicks / resubmits of the embedded form creating
    several copies of the same lead. The window (in seconds) is configurable
    with settings.WEB_TO_LEAD_DUPLICATE_WINDOW; 0 disables the check.
    """
    window = getattr(settings, "WEB_TO_LEAD_DUPLICATE_WINDOW", 300)
    if not window:
        return None

    lookup = {}
    for name, value in cleaned_data.items():
        try:
            Lead._meta.get_field(name)
        except FieldDoesNotExist:
            continue  # extension field, not a Lead column
        if isinstance(value, (list, tuple, set, QuerySet)):
            continue  # many-to-many values can't be matched with a plain lookup
        if isinstance(value, str) and name == "email":
            lookup["email__iexact"] = value.strip()
        else:
            lookup[name] = value

    return (
        Lead.all_objects.filter(
            company=form_config.company,
            lead_source="website",
            created_at__gte=timezone.now() - timedelta(seconds=window),
            **lookup,
        )
        .order_by("-created_at")
        .first()
    )


def render_form_preview(fields, form_name, color, language):
    """Render the builder preview in the form language without changing the UI locale."""
    with translation.override(language or "en"):
        return render_to_string(
            "web_to_lead/form_preview.html",
            {
                "fields": fields,
                "form_name": form_name,
                "color": color,
                "LANGUAGE_BIDI": translation.get_language_bidi(),
            },
        )


def _form_field_info(name, field):
    """Describe an extension form field the way the builder/public templates expect."""
    choices = getattr(field, "choices", None)
    if choices:
        choices = [(v, label) for v, label in choices if v not in ("", None)]
    if isinstance(field, forms.MultipleChoiceField):
        field_type = "MultipleChoiceField"
    elif choices:
        field_type = "ChoiceField"
    elif isinstance(field, forms.DateTimeField):
        field_type = "DateTimeField"
    elif isinstance(field, forms.DateField):
        field_type = "DateField"
    elif isinstance(field, forms.DecimalField):
        field_type = "DecimalField"
    elif isinstance(field.widget, forms.Textarea):
        field_type = "TextField"
    else:
        field_type = "CharField"
    return {
        "name": name,
        "verbose_name": str(field.label or name),
        "required": field.required,
        "field_type": field_type,
        "choices": choices or None,
    }


def get_extension_form_fields():
    """Return ``{name: form field}`` that extensions add to the Lead form beyond model columns."""
    extra = {}
    for name, field in resolve_form_class(WebToLeadForm)().fields.items():
        try:
            Lead._meta.get_field(name)
        except FieldDoesNotExist:
            extra[name] = field
    return extra


def get_field_info(field_name, extension_fields=None):
    """Return builder/preview metadata for a Lead column or an extension field, or None."""
    try:
        field = Lead._meta.get_field(field_name)
    except FieldDoesNotExist:
        if extension_fields is None:
            extension_fields = get_extension_form_fields()
        extra = extension_fields.get(field_name)
        return _form_field_info(field_name, extra) if extra else None
    return {
        "name": field_name,
        "verbose_name": str(getattr(field, "verbose_name", field_name)),
        "required": not getattr(field, "blank", False),
        "field_type": field.get_internal_type(),
        "choices": (
            field.choices if hasattr(field, "choices") and field.choices else None
        ),
    }


def get_preview_fields_data(selected_fields):
    """Build field metadata (verbose name, type, choices) for form preview rendering."""
    extension_fields = get_extension_form_fields()
    fields_data = []
    for field_name in dict.fromkeys(selected_fields):  # drop duplicate selections
        info = get_field_info(field_name, extension_fields)
        if info:
            fields_data.append(info)
    return fields_data


def get_builder_lead_fields():
    """Return the Lead columns plus extension fields offered in the form builder."""
    lead_fields = []
    for field in Lead._meta.get_fields():
        if (
            field.concrete
            and not field.auto_created
            and field.name not in exclude_fields
        ):
            lead_fields.append(
                {
                    "name": field.name,
                    "verbose_name": getattr(field, "verbose_name", field.name),
                    "required": not getattr(field, "blank", False),
                    "field_type": field.get_internal_type(),
                }
            )
    lead_fields.extend(
        _form_field_info(name, field)
        for name, field in get_extension_form_fields().items()
    )
    return lead_fields


# Fields to exclude from web-to-lead form builder (avoid repeating in views)
exclude_fields = [
    "id",
    "is_active",
    "created_at",
    "updated_at",
    "is_convert",
    "converted_contact",
    "converted_opportunity",
    "converted_at",
    "additional_info",
    "created_by",
    "updated_by",
    "lead_score",
    "message_id",
    "lead_owner",
    "lead_status",
    "company",
    "lead_source",
    "requirements",
]


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied("leads.add_leadcaptureform"), name="dispatch"
)
class LeadFormBuilderNavbar(LoginRequiredMixin, HorillaNavView):
    """Navbar for the web-to-lead form builder (Edit / Cancel / Generate)."""

    nav_title = _("Lead Capture Form")
    nav_description = _("Build a web form to capture leads directly from your website.")
    nav_width = False
    search_option = False
    all_view_types = False
    recently_viewed_option = False
    filter_option = False
    one_view_only = True
    reload_option = False
    border_enabled = False

    @cached_property
    def has_saved_form(self):
        """Whether the active company already has a saved capture form."""
        return LeadCaptureForm.objects.filter(
            company=self.request.active_company, is_active=True
        ).exists()

    @cached_property
    def is_editing(self):
        """Whether the builder is open for editing (or first-time creation)."""
        return bool(self.request.GET.get("edit")) or not self.has_saved_form

    @cached_property
    def new_button(self):
        """Edit Form in view mode, Generate while building."""
        # hx-disable stops the navbar's default hx-get so onclick alone drives it
        if not self.is_editing:
            return {
                "url": reverse("leads:form_builder"),
                "title": _("Edit Form"),
                "onclick": "window.location.href='"
                + reverse("leads:form_builder")
                + "?edit=1'",
                "attrs": {"hx-disable": "true"},
            }
        return {
            "url": reverse("leads:save_form"),
            "title": _("Generate"),
            "onclick": "document.getElementById('formBuilderForm').requestSubmit()",
            "attrs": {"hx-disable": "true"},
        }

    @cached_property
    def second_button(self):
        """Cancel, only when editing an already saved form."""
        if self.is_editing and self.has_saved_form:
            return {
                "url": reverse("leads:form_builder"),
                "title": _("Cancel"),
                "onclick": "window.location.href='"
                + reverse("leads:form_builder")
                + "'",
                "attrs": {"hx-disable": "true"},
            }
        return None


@method_decorator(
    permission_required_or_denied("leads.add_leadcaptureform"), name="dispatch"
)
class LeadFormBuilderView(LoginRequiredMixin, TemplateView):
    """View for building lead capture forms"""

    template_name = "web_to_lead/lead_form_builder.html"
    action = None  # allow parameter

    def get_context_data(self, **kwargs):
        """Build form-builder context with lead fields and available owners."""
        context = super().get_context_data(**kwargs)

        lead_fields = get_builder_lead_fields()
        context["lead_fields"] = lead_fields
        context["nav_url"] = reverse("leads:form_builder_nav_bar")
        context["lead_owners"] = User.objects.filter(is_active=True)

        saved_form = LeadCaptureForm.objects.filter(
            company=self.request.active_company, is_active=True
        ).first()
        if saved_form:
            context["saved_form"] = saved_form
            context["form_url"] = build_public_form_url(self.request, saved_form.id)

            if not saved_form.generated_html:
                translation.activate(saved_form.language)
                selected_fields = json.loads(saved_form.selected_fields)
                saved_form.generated_html = render_to_string(
                    "web_to_lead/public_lead_form.html",
                    {
                        "form_obj": saved_form,
                        "selected_fields_parsed": get_preview_fields_data(
                            selected_fields
                        ),
                        "form_id": saved_form.id,
                        "view": {"kwargs": {"form_id": saved_form.id}},
                        "submit_url": context["form_url"],
                    },
                )
                saved_form.save(update_fields=["generated_html"])
                translation.deactivate()

            if self.request.GET.get("edit"):
                selected_fields = list(
                    dict.fromkeys(parse_selected_fields(saved_form.selected_fields))
                )
                context["form_data"] = {
                    "form_name": saved_form.form_name,
                    "return_url_enable": saved_form.return_url_enable,
                    "return_url": saved_form.return_url,
                    "success_message": saved_form.success_message,
                    "success_description": saved_form.success_description,
                    "language": saved_form.language,
                    "color": saved_form.header_color,
                    "selected_fields": selected_fields,
                    "lead_owner": saved_form.lead_owner_id,
                    "apply_assignment_rule": saved_form.apply_assignment_rule,
                }
                context["preview_fields"] = get_preview_fields_data(selected_fields)
                context["preview_html"] = mark_safe(
                    render_form_preview(
                        context["preview_fields"],
                        saved_form.form_name,
                        saved_form.header_color,
                        saved_form.language,
                    )
                )
        return context


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied("leads.add_leadcaptureform"), name="dispatch"
)
class UpdateFormHeadingView(LoginRequiredMixin, TemplateView):
    """HTMX view to update form heading"""

    template_name = "web_to_lead/form_heading.html"

    def post(self, request, *args, **kwargs):
        """Handle POST request to update form heading."""
        form_name = request.POST.get("form_name", "").strip()
        color = request.POST.get("color", "")

        language = request.POST.get("language", "en")  # Add language

        context = {
            "form_name": form_name if form_name else "Contact Us",
            "color": color,
            "language": language,  # Pass to template
        }

        return render(request, self.template_name, context)


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied("leads.add_leadcaptureform"), name="dispatch"
)
class UpdateFormPreviewView(LoginRequiredMixin, TemplateView):
    """HTMX view to update form preview"""

    template_name = "web_to_lead/form_preview.html"

    def post(self, request, *args, **kwargs):
        """Handle POST request to update form preview."""

        selected_fields = request.POST.getlist("selected_fields[]")
        form_name = request.POST.get("form_name", "").strip()
        color = request.POST.get("color")
        language = request.POST.get("language", "en")
        fields_data = get_preview_fields_data(selected_fields)
        return HttpResponse(
            render_form_preview(fields_data, form_name, color, language)
        )


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied("leads.add_leadcaptureform"), name="dispatch"
)
class SaveLeadFormView(LoginRequiredMixin, FormView):
    """View to save lead capture form configuration - one per company"""

    model = LeadCaptureForm
    fields = [
        "form_name",
        "return_url_enable",
        "return_url",
        "success_message",
        "success_description",
        "enable_recaptcha",
        "language",
        "header_color",
    ]
    success_url = reverse_lazy("leads:form_builder")
    template_name = "web_to_lead/lead_form_builder.html"

    def get_form_class(self):
        """Dynamically create the form class."""
        from django.forms import ModelForm

        class LeadCaptureFormForm(ModelForm):
            """Form for lead capture form configuration."""

            class Meta:
                """Meta options for LeadCaptureFormForm."""

                model = LeadCaptureForm
                fields = self.fields

        return LeadCaptureFormForm

    def form_valid(self, form):
        """Validate, save, and generate embed HTML for lead capture form config."""
        # Validate lead owner
        lead_owner = self.request.POST.get("lead_owner")
        if not lead_owner:
            form.add_error("lead_owner", _("Lead Owner is required."))
            return self.form_invalid(form)

        # Validate selected fields
        selected_fields = self.request.POST.getlist("selected_fields[]")
        if not selected_fields:
            form.add_error(None, _("Select at least one field."))
            return self.form_invalid(form)

        # Validate return URL requirements
        return_url_enable = self.request.POST.get("return_url_enable") == "on"

        if return_url_enable:
            return_url = form.cleaned_data.get("return_url")
            if not return_url:
                form.add_error("return_url", _("Return URL is required when enabled."))
                return self.form_invalid(form)
        else:
            success_message = form.cleaned_data.get("success_message")
            success_description = form.cleaned_data.get("success_description")
            if not success_message:
                form.add_error("success_message", _("Success message is required."))
                return self.form_invalid(form)
            if not success_description:
                form.add_error(
                    "success_description", _("Success description is required.")
                )
                return self.form_invalid(form)

        # Get or create the LeadCaptureForm instance
        obj, _created = LeadCaptureForm.objects.get_or_create(
            company=self.request.active_company,
            defaults={
                "created_by": self.request.user,
                "lead_owner_id": lead_owner,
                "form_name": form.cleaned_data.get("form_name", "Contact Us"),
                "language": form.cleaned_data.get("language", "en"),
                "header_color": self.request.POST.get("color", ""),
            },
        )

        # Update the instance with form data
        obj.form_name = form.cleaned_data.get("form_name")
        obj.language = form.cleaned_data.get("language")
        obj.enable_recaptcha = form.cleaned_data.get("enable_recaptcha", False)
        obj.created_by = self.request.user
        obj.lead_owner_id = lead_owner
        obj.apply_assignment_rule = (
            self.request.POST.get("apply_assignment_rule") == "on"
        )
        obj.selected_fields = json.dumps(selected_fields)
        obj.header_color = self.request.POST.get("color")
        obj.return_url_enable = return_url_enable

        if return_url_enable:
            obj.return_url = form.cleaned_data.get("return_url")
            obj.success_message = None
            obj.success_description = None
        else:
            obj.success_message = form.cleaned_data.get("success_message")
            obj.success_description = form.cleaned_data.get("success_description")
            obj.return_url = None

        # Activate selected language for form generation
        selected_language = obj.language
        translation.activate(selected_language)

        obj.save()
        self.object = obj

        # Parse selected fields for form generation
        parsed_fields = get_preview_fields_data(selected_fields)

        # Generate HTML code
        submit_url = build_public_form_url(self.request, self.object.id)
        html_code = render_to_string(
            "web_to_lead/public_lead_form.html",
            {
                "form_obj": self.object,
                "selected_fields_parsed": parsed_fields,
                "form_id": self.object.id,
                "LANGUAGE_BIDI": translation.get_language_bidi(),
                "view": {"kwargs": {"form_id": self.object.id}},
                "submit_url": submit_url,
            },
        )

        self.object.generated_html = html_code
        self.object.save()

        translation.deactivate()

        # Return response
        if self.request.headers.get("HX-Request"):
            response = HttpResponse()
            response["HX-Redirect"] = reverse("leads:form_builder")
            return response

        return RedirectResponse(request=self.request, redirect_to=self.success_url)

    def form_invalid(self, form):
        """Re-render builder with errors, preserving submitted data for HTMX."""
        if self.request.headers.get("HX-Request"):
            # Get lead fields for the form builder
            lead_fields = get_builder_lead_fields()

            # Preserve form data for re-rendering
            form_data = {
                "form_name": self.request.POST.get("form_name", "Contact Us"),
                "return_url_enable": self.request.POST.get("return_url_enable") == "on",
                "return_url": self.request.POST.get("return_url", ""),
                "success_message": self.request.POST.get("success_message", ""),
                "success_description": self.request.POST.get("success_description", ""),
                "language": self.request.POST.get("language", "en"),
                "color": self.request.POST.get("color", ""),
                "selected_fields": self.request.POST.getlist("selected_fields[]"),
                "lead_owner": self.request.POST.get("lead_owner"),
            }

            preview_fields = get_preview_fields_data(form_data["selected_fields"])
            context = {
                "form": form,
                "errors": form.errors,
                "lead_fields": lead_fields,
                "form_data": form_data,
                "lead_owners": User.objects.filter(is_active=True),
                "preview_fields": preview_fields,
                "preview_html": mark_safe(
                    render_form_preview(
                        preview_fields,
                        form_data["form_name"],
                        form_data["color"],
                        form_data["language"],
                    )
                ),
            }

            response = render(self.request, self.template_name, context)
            response["HX-Reselect"] = "#formBuilderForm"
            return response
        return super().form_invalid(form)


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied("leads.add_leadcaptureform"), name="dispatch"
)
class AddFieldView(LoginRequiredMixin, TemplateView):
    """HTMX view to add a field to selected list"""

    template_name = "web_to_lead/selected_field.html"

    def post(self, request, *args, **kwargs):
        """Handle POST request to add a field to selected list."""
        field_name = request.POST.get("field_name")
        field_verbose = request.POST.get("field_verbose")
        form_name = request.POST.get("form_name")
        language = request.POST.get("language", "en")  # Add language

        context = {
            "field_name": field_name,
            "field_verbose": field_verbose,
            "form_name": form_name,
            "language": language,  # Pass to template
        }

        # Trigger preview update after field is added
        response = render(request, self.template_name, context)
        response["HX-Trigger"] = "updatePreview"
        return response


@method_decorator(
    permission_required_or_denied("leads.add_leadcaptureform"), name="dispatch"
)
class RemoveFieldView(LoginRequiredMixin, View):
    """HTMX view to remove a field from selected list."""

    def post(self, request, *args, **kwargs):
        """Handle POST request to remove a field from selected list."""
        field_name = request.POST.get("field_name")
        # Escape for safe embedding in JavaScript (prevents XSS)
        field_name_escaped = js_json(field_name) if field_name is not None else '""'
        context = {"field_name_escaped": field_name_escaped}
        response = render(request, "web_to_lead/remove_field_script.html", context)
        response["HX-Trigger"] = "updatePreview"
        return response


@method_decorator(xframe_options_exempt, name="dispatch")
@method_decorator(csrf_exempt, name="dispatch")
class PublicLeadFormView(CreateView):
    """Public view for lead submission with HTMX support.

    Meant to be embedded (iframe) or POSTed to from any external website, so
    framing and CORS are open for this view only (not project-wide). Spam is
    limited with a per-IP rate limit, a honeypot field and duplicate detection.
    """

    model = Lead
    template_name = "web_to_lead/public_lead_form.html"

    def dispatch(self, request, *args, **kwargs):
        """Rate-limit submissions and add CORS headers for embedding on any site."""
        form_id = kwargs.get("form_id")

        if request.method == "OPTIONS":
            response = HttpResponse(status=204)
        elif request.method == "POST" and (
            # Hidden field real visitors never fill; bots usually do
            request.POST.get("hp_check")
            or _public_form_rate_limited(request, form_id)
        ):
            response = HttpResponse(status=429)
        else:
            response = super().dispatch(request, *args, **kwargs)

        # The form is anonymous and sends no credentials, so echoing the origin
        # only lets other sites read the response of their own submission.
        origin = request.META.get("HTTP_ORIGIN")
        if origin:
            response["Access-Control-Allow-Origin"] = origin
            response["Access-Control-Allow-Methods"] = "POST, OPTIONS"
            response["Access-Control-Allow-Headers"] = (
                request.META.get("HTTP_ACCESS_CONTROL_REQUEST_HEADERS")
                or "Content-Type, HX-Request, HX-Current-URL"
            )
            response["Vary"] = "Origin"
        return response

    def get_form_class(self):
        """Get form class for public lead form based on form configuration."""
        form_id = self.kwargs.get("form_id")
        try:
            form_config = LeadCaptureForm.objects.get(id=form_id, is_active=True)

            # Activate the form's language
            translation.activate(form_config.language)

            return resolve_form_class(WebToLeadForm)
        except LeadCaptureForm.DoesNotExist as e:
            raise HttpNotFound(
                str(e), template="web_to_lead/web_to_lead_404.html"
            ) from e

    def get_form(self, form_class=None):
        """Keep only the fields selected in the lead-capture form configuration."""
        form = super().get_form(form_class)
        form_config = LeadCaptureForm.objects.get(
            id=self.kwargs.get("form_id"), is_active=True
        )
        selected = parse_selected_fields(form_config.selected_fields)
        for name in list(form.fields):
            if name not in selected:
                del form.fields[name]
        return form

    def get_context_data(self, **kwargs):
        """Populate public form context from stored lead-capture configuration."""
        context = super().get_context_data(**kwargs)
        form_id = self.kwargs.get("form_id")
        context["submit_url"] = build_public_form_url(self.request, form_id)

        try:
            form_config = LeadCaptureForm.objects.get(id=form_id, is_active=True)

            # Activate the form's language
            translation.activate(form_config.language)

            context["form_obj"] = form_config
            context["form_config"] = form_config

            # Parse selected fields for template
            selected_fields = parse_selected_fields(form_config.selected_fields)
            parsed_fields = get_preview_fields_data(selected_fields)
            for field_info in parsed_fields:
                # Handle ForeignKey and OneToOneField
                if field_info["field_type"] in ("ForeignKey", "OneToOneField"):
                    related_model = Lead._meta.get_field(
                        field_info["name"]
                    ).related_model
                    field_info["choices"] = [
                        (obj.pk, str(obj)) for obj in related_model.objects.all()
                    ]

            context["selected_fields_parsed"] = parsed_fields

        except LeadCaptureForm.DoesNotExist as e:
            raise HttpNotFound(
                str(e), template="web_to_lead/web_to_lead_404.html"
            ) from e

        return context

    def form_valid(self, form):
        """Create a lead and return HTMX redirect or success fragment."""
        form_id = self.kwargs.get("form_id")
        with transaction.atomic():
            # Lock the form config so concurrent submissions (e.g. a double
            # click on the embedded form) are checked for duplicates one at a time.
            form_config = LeadCaptureForm.objects.select_for_update().get(id=form_id)
            duplicate = find_recent_duplicate_lead(form_config, form.cleaned_data)
            if duplicate:
                self.object = duplicate
            else:
                form.instance.lead_owner = form_config.lead_owner
                if not form_config.apply_assignment_rule:
                    form.instance._skip_assignment_rule = True
                form.instance.company = form_config.company
                form.instance.lead_source = "website"
                try:
                    form.instance.lead_status = LeadStatus.objects.first()
                except Exception:
                    pass

                self.object = form.save()

        # Check if this is an HTMX request
        if self.request.headers.get("HX-Request"):
            # Check if return URL exists
            if form_config.return_url and form_config.return_url.strip():
                return_url = form_config.return_url.strip()

                # Parse the URL to check if it's external
                parsed_url = urlparse(return_url)

                # If no scheme is present, add https://
                if not parsed_url.scheme:
                    if return_url.startswith("/"):
                        # It's a relative URL on the same domain
                        response = HttpResponse()
                        response["HX-Redirect"] = return_url
                        return response
                    return_url = "https://" + return_url

                # External redirect via HTMX
                response = HttpResponse()
                response["HX-Redirect"] = return_url
                return response

            header_color = form_config.header_color or "hsl(8, 77%, 56%)"
            success_message = (
                form_config.success_message
                if form_config.success_message
                else "Thank you!"
            )
            success_description = (
                form_config.success_description
                if form_config.success_description
                else "We have received your information and will get back to you soon."
            )

            return render(
                self.request,
                "web_to_lead/form_success.html",
                {
                    "header_color": header_color,
                    "success_message": success_message,
                    "success_description": success_description,
                },
            )
        return ""

    def form_invalid(self, form):
        """Handle invalid form submission for HTMX and non-HTMX requests."""
        # For HTMX requests, return the form with errors
        if self.request.headers.get("HX-Request"):
            return self.render_to_response(self.get_context_data(form=form))

        # Non-HTMX fallback
        return super().form_invalid(form)


@method_decorator(
    permission_required_or_denied("leads.add_leadcaptureform"), name="dispatch"
)
class ToggleReturnUrlView(LoginRequiredMixin, View):
    """Toggle between return URL and success message fields"""

    def post(self, request, *args, **kwargs):
        """Handle POST request to toggle return URL fields."""
        return_url_enabled = request.POST.get("return_url_enable") == "on"

        context = {"return_url_enabled": return_url_enabled}
        return render(request, "web_to_lead/conditional_fields.html", context)
