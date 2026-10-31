"""HTMX-friendly views to load mail templates and create default automations from installed apps."""

# Standard library imports
import json
import logging
from pathlib import Path

# Third-party imports (Django)
from django.contrib import messages

from horilla.apps import apps
from horilla.auth.mixins import LoginRequiredMixin
from horilla.contrib.core.models import HorillaContentType
from horilla.contrib.mail.models import HorillaMailConfiguration, HorillaMailTemplate
from horilla.utils.decorators import (
    htmx_required,
    method_decorator,
    permission_required_or_denied,
)
from horilla.utils.translation import gettext_lazy as _

# First-party imports (Horilla)
from horilla.views.generic import TemplateView, View
from horilla.web import ScriptResponse

# Local imports
from .models import HorillaAutomation, normalize_delivery_channels

logger = logging.getLogger(__name__)


def _get_company(request):
    return getattr(request, "active_company", getattr(request.user, "company", None))


def _ensure_mail_templates_loaded(request):
    """
    Load mail templates from all apps that define template_files.
    Creates HorillaMailTemplate if not exists (by title + company).
    Returns dict mapping JSON pk -> HorillaMailTemplate instance for current company.
    """
    company = _get_company(request)
    template_map = {}  # json pk -> HorillaMailTemplate

    for app_config in apps.get_app_configs():
        template_files = getattr(app_config, "template_files", [])
        if not template_files:
            continue
        app_path = Path(app_config.path)
        for template_file in template_files:
            json_path = app_path / template_file
            if not json_path.exists():
                continue
            try:
                with open(json_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
            except Exception as e:
                print(f"Error loading {json_path}: {e}")
                continue

            for idx, entry in enumerate(data):
                if entry.get("model") != "mail.horillamailtemplate":
                    continue
                fields = entry["fields"]
                title = fields["title"]
                json_pk = entry.get("pk", idx + 1)
                subject = fields.get("subject") or ""
                body = fields.get("body") or ""
                content_type = None
                ct_info = fields.get("content_type")
                if ct_info and isinstance(ct_info, dict):
                    app_label = ct_info.get("app_label")
                    model_name = ct_info.get("model")
                    if app_label and model_name:
                        try:
                            content_type = HorillaContentType.objects.get(
                                app_label=app_label, model=model_name
                            )
                        except HorillaContentType.DoesNotExist:
                            pass

                template, created = HorillaMailTemplate.objects.get_or_create(
                    title=title,
                    company=company,
                    defaults={
                        "subject": subject,
                        "body": body,
                        "content_type": content_type,
                        "is_active": fields.get("is_active", True),
                        "created_by": request.user,
                        "updated_by": request.user,
                    },
                )
                if not created:
                    template.updated_by = request.user
                    template.save(update_fields=["updated_at", "updated_by"])
                template_map[json_pk] = template

    return template_map


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied(["automations.add_horillaautomation"]),
    name="dispatch",
)
class LoadAutomationModalView(LoginRequiredMixin, TemplateView):
    """Modal view: load mail templates first, then list default automations and mail servers."""

    template_name = "load_automation.html"

    def get_context_data(self, **kwargs):
        """Load mail templates, collect default automations from app automation_files, and add mail servers to context."""
        context = super().get_context_data(**kwargs)

        all_automations = []
        for app_config in apps.get_app_configs():
            automation_files = getattr(app_config, "automation_files", [])
            app_path = Path(app_config.path)
            for automation_file in automation_files:
                json_path = app_path / automation_file
                if not json_path.exists():
                    continue
                try:
                    with open(json_path, "r", encoding="utf-8") as f:
                        data = json.load(f)
                except Exception as e:
                    print(f"Error loading {json_path}: {e}")
                    continue
                for entry in data:
                    if entry.get("model") != "automations.horillaautomation":
                        continue
                    fields = entry["fields"]
                    all_automations.append(
                        {
                            "title": fields.get("title", ""),
                            "trigger": fields.get("trigger", ""),
                            "module": app_config.verbose_name or app_config.label,
                            "app_label": app_config.label,
                            "source_file": automation_file,
                        }
                    )
        context["automations"] = all_automations
        company = _get_company(self.request)
        mail_servers = HorillaMailConfiguration.objects.filter(mail_channel="outgoing")
        if company:
            mail_servers = mail_servers.filter(company=company)
        context["mail_servers"] = list(mail_servers)
        return context


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied(["automations.add_horillaautomation"]),
    name="dispatch",
)
class CreateSelectedAutomationsView(LoginRequiredMixin, View):
    """Create selected default automations with the chosen mail server and loaded templates."""

    def post(self, request, *args, **kwargs):
        """Create selected automations using the chosen mail server; return script or error response."""
        mail_server_id = request.POST.get("mail_server")
        selected_titles = request.POST.getlist("selected_automations")

        if not mail_server_id:
            messages.error(request, _("Please select a mail server."))
            return ScriptResponse(
                close=True,
                status=400,
            )

        company = _get_company(request)
        try:
            mail_server = HorillaMailConfiguration.objects.get(
                pk=mail_server_id,
                mail_channel="outgoing",
            )
            if company and mail_server.company != company:
                mail_server = None
        except (HorillaMailConfiguration.DoesNotExist, ValueError):
            mail_server = None
        if not mail_server:
            messages.error(request, _("Invalid mail server selected."))
            return ScriptResponse(
                close=True,
                status=400,
            )

        # Ensure templates are loaded and get json pk -> template map
        template_map = _ensure_mail_templates_loaded(request)
        created = []
        skipped = []

        for app_config in apps.get_app_configs():
            automation_files = getattr(app_config, "automation_files", [])
            app_path = Path(app_config.path)
            for automation_file in automation_files:
                json_path = app_path / automation_file
                if not json_path.exists():
                    continue
                try:
                    with open(json_path, "r", encoding="utf-8") as f:
                        data = json.load(f)
                except Exception as e:
                    print(f"Error loading {json_path}: {e}")
                    continue
                for entry in data:
                    if entry.get("model") != "automations.horillaautomation":
                        continue
                    fields = entry["fields"]
                    title = fields.get("title", "")
                    if title not in selected_titles:
                        continue
                    if HorillaAutomation.objects.filter(title=title).exists():
                        skipped.append(title)
                        continue
                    # Resolve mail_template from JSON pk
                    json_template_pk = fields.get("mail_template")
                    mail_template = (
                        template_map.get(json_template_pk) if json_template_pk else None
                    )
                    # Resolve model (ContentType)
                    model_ct = None
                    model_info = fields.get("model")
                    if isinstance(model_info, dict):
                        al = model_info.get("app_label")
                        mn = model_info.get("model")
                        if al and mn:
                            try:
                                model_ct = HorillaContentType.objects.get(
                                    app_label=al, model=mn
                                )
                            except HorillaContentType.DoesNotExist:
                                continue
                    if not model_ct:
                        continue
                    # This loader does not use the form: a seed "both" is
                    # written as "mail,notification", and a row whose delivery
                    # channel is not registered here is skipped.
                    delivery_channel, unknown = normalize_delivery_channels(
                        fields.get("delivery_channel", "mail"), company
                    )
                    if unknown or not delivery_channel:
                        logger.warning(
                            "Automation %s not loaded: delivery channel %s is not "
                            "registered",
                            title,
                            ", ".join(unknown) or fields.get("delivery_channel"),
                        )
                        continue
                    HorillaAutomation.objects.create(
                        title=title,
                        method_title=title.replace(" ", "_").lower(),
                        model=model_ct,
                        mail_to=fields.get("mail_to", ""),
                        trigger=fields.get("trigger", "on_create"),
                        mail_template=mail_template,
                        mail_server=mail_server,
                        delivery_channel=delivery_channel,
                        is_active=fields.get("is_active", True),
                        company=company,
                        created_by=request.user,
                        updated_by=request.user,
                    )
                    created.append(title)

        if created and skipped:
            messages.success(
                request,
                f"{len(created)} automation(s) loaded. {len(skipped)} already exist and were skipped.",
            )
        elif created:
            messages.success(request, _("Automations loaded successfully."))
        elif skipped:
            messages.warning(request, _("All selected automations already exist."))
        else:
            messages.info(request, _("No automations were processed."))

        return ScriptResponse(reload=True, close=True)
