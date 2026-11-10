"""
Adds the WhatsApp channel's fields to the Automation form, through extensions
only (nothing in the Automations app is edited):

* ``AutomationWhatsAppFormExtension`` (``_inherit_form``) appends the
  ``whatsapp_account`` / ``whatsapp_template`` columns that
  ``AutomationWhatsAppExtension`` (models.py) injects onto the automation,
  and validates them when the WhatsApp channel is selected.
* ``AutomationWhatsAppFieldsExtension`` (``_inherit_view``) makes the form's
  channel selector show or hide those two fields, next to the mail and
  notification template fields it already toggles.
"""

# Third-party imports (Django)
from django.template.loader import render_to_string

# First party imports (Horilla)
from horilla.contrib.core.models import HorillaContentType
from horilla.extension.forms import FormExtension
from horilla.extension.view import ViewExtension
from horilla.utils.translation import gettext_lazy as _

from .delivery import unsupported_reason

CHANNEL_KEY = "whatsapp"


def _split_channels(value):
    """The channel keys in a comma separated stored value or a list of them."""
    if isinstance(value, (list, tuple)):
        value = ",".join(str(key) for key in value)
    return [key.strip() for key in (value or "").split(",") if key.strip()]


def active_accounts(company=None):
    """The company's active WhatsApp accounts, the primary one first."""
    from .models import WhatsAppAccount

    accounts = WhatsAppAccount.objects.filter(is_active=True)
    if company:
        accounts = accounts.filter(company=company)
    return accounts.order_by("-is_primary", "pk")


def usable_templates(company=None, content_type=None):
    """
    Active WhatsApp templates an automation can send: the company's (or
    company-less) templates for the automation's module, minus ones an
    automation can't send: variables not yet linked to record fields on the
    template, a header value or media, a carousel, a button value.
    """
    from django.db.models import Q

    from .models import WhatsAppTemplate

    queryset = WhatsAppTemplate.objects.filter(is_active=True)
    if company:
        queryset = queryset.filter(Q(company=company) | Q(company__isnull=True))
    if content_type:
        queryset = queryset.filter(
            Q(content_type=content_type) | Q(content_type__isnull=True)
        )
    usable = []
    for template in queryset.order_by("title"):
        if unsupported_reason(template):
            continue
        usable.append(template)
    return usable


class AutomationWhatsAppFormExtension(FormExtension):
    """Add and validate the WhatsApp account and template fields on the automation form."""

    _inherit_form = "horilla.contrib.automations.forms.HorillaAutomationForm"

    class Meta:
        fields_append = ["whatsapp_account", "whatsapp_template"]

    def setup_form_extension_fields(self):
        """Style the fields, limit the choices, and keep them when the channel changes."""
        request = getattr(self, "request", None)
        company = None
        if request is not None and getattr(request, "user", None):
            company = getattr(request, "active_company", None) or getattr(
                request.user, "company", None
            )
        content_type = None
        model_name = getattr(self, "model_name", None)
        if model_name:
            content_type = HorillaContentType.objects.filter(
                model=str(model_name).lower()
            ).first()

        if "whatsapp_account" in self.fields:
            field = self.fields["whatsapp_account"]
            field.required = False
            field.empty_label = "---------"
            field.queryset = active_accounts(company)
            field.widget.attrs.update({"class": "js-example-basic-single headselect"})
        if "whatsapp_template" in self.fields:
            field = self.fields["whatsapp_template"]
            field.required = False
            field.queryset = field.queryset.filter(
                pk__in=[t.pk for t in usable_templates(company, content_type)]
            )
            field.widget.attrs.update({"class": "js-example-basic-single headselect"})

        self._place_and_hide_whatsapp_fields()

        # The channel selector reloads the WhatsApp fields; send their values
        # along so changing channels doesn't blank what was already chosen.
        if "delivery_channel" in self.fields:
            attrs = self.fields["delivery_channel"].widget.attrs
            include = attrs.get("hx-include", "")
            extra = "[name='whatsapp_account'],[name='whatsapp_template']"
            if include and extra not in include:
                attrs["hx-include"] = f"{include},{extra}"

    def _place_and_hide_whatsapp_fields(self):
        """
        Put the WhatsApp fields right under the delivery channel, and start every
        channel-specific field (WhatsApp, mail template, notification template, mail
        server) shown or hidden to match the selected channels, so nothing flashes
        before the form's own reload corrects it.
        """
        from horilla.registry.delivery import get_delivery_channel

        ours = [
            name
            for name in ("whatsapp_account", "whatsapp_template")
            if name in self.fields
        ]
        names = [name for name in self.fields if name not in ours]
        anchor = next(
            (
                n
                for n in ("notification_template", "mail_template", "delivery_channel")
                if n in names
            ),
            None,
        )
        if anchor:
            # After the mail and notification fields, so the order follows the channels.
            position = names.index(anchor) + 1
            self.order_fields(names[:position] + ours + names[position:])

        current = getattr(self, "_current_delivery_channels", None)
        keys = _split_channels(current() if callable(current) else None)
        channels = [
            c for c in (get_delivery_channel(key) for key in keys) if c is not None
        ]
        visible = {
            "whatsapp_account": CHANNEL_KEY in keys,
            "whatsapp_template": CHANNEL_KEY in keys,
            "mail_template": any(c.shows_mail_fields() for c in channels),
            "mail_server": any(c.shows_mail_fields() for c in channels),
            "notification_template": any(
                c.shows_notification_fields() for c in channels
            ),
        }
        for name, is_visible in visible.items():
            if name not in self.fields:
                continue
            attrs = self.fields[name].widget.attrs
            if is_visible:
                attrs.pop("container_style", None)
            else:
                attrs["container_style"] = "display: none"

    def clean(self):
        """When WhatsApp is a selected channel, the account and a usable template are required."""
        cleaned = super().clean()
        if CHANNEL_KEY not in _split_channels(cleaned.get("delivery_channel")):
            return cleaned

        account = cleaned.get("whatsapp_account")
        template = cleaned.get("whatsapp_template")
        if not account:
            self.add_error(
                None, _("WhatsApp: choose the WhatsApp account to send from.")
            )
        if not template:
            self.add_error(None, _("WhatsApp: choose a WhatsApp template."))
            return cleaned
        reason = unsupported_reason(template)
        if reason:
            self.add_error(
                None,
                _(
                    "WhatsApp: %(title)s can't be sent from an automation because %(reason)s."
                )
                % {"title": template.title, "reason": reason},
            )
            return cleaned
        if account and template.account_id and template.account_id != account.pk:
            self.add_error(
                None,
                _(
                    "WhatsApp: %(title)s belongs to the account %(owner)s, not %(account)s."
                )
                % {
                    "title": template.title,
                    "owner": template.account,
                    "account": account,
                },
            )
        return cleaned


class AutomationWhatsAppFieldsExtension(ViewExtension):
    """Show or hide the WhatsApp fields when the channel selector changes."""

    _inherit_view = "horilla.contrib.automations.views.TemplateFieldsView"

    def get(self, request, *args, **kwargs):
        response = super().get(request, *args, **kwargs)

        from horilla.contrib.automations.models import HorillaAutomation

        channels = _split_channels(
            ",".join(request.GET.getlist("delivery_channel", ["mail"]))
        )
        show = CHANNEL_KEY in channels

        template_id = request.GET.get("whatsapp_template") or None
        account_id = request.GET.get("whatsapp_account") or None
        content_type = None
        model_id = request.GET.get("model")
        if model_id and str(model_id).isdigit():
            content_type = HorillaContentType.objects.filter(pk=model_id).first()
        automation_id = request.GET.get("automation_id")
        automation = None
        if automation_id:
            automation = HorillaAutomation.objects.filter(pk=automation_id).first()
            if automation:
                content_type = content_type or automation.model
                if template_id is None and automation.whatsapp_template_id:
                    template_id = automation.whatsapp_template_id
                if account_id is None and automation.whatsapp_account_id:
                    account_id = automation.whatsapp_account_id

        company = getattr(request, "active_company", None) or request.user.company

        field = HorillaAutomation._meta.get_field
        html = render_to_string(
            "whatsapp_automation/template_fields.html",
            {
                "show": show,
                "accounts": active_accounts(company) if show else [],
                "templates": usable_templates(company, content_type) if show else [],
                "selected_account": (
                    int(account_id) if str(account_id or "").isdigit() else None
                ),
                "selected_template": (
                    int(template_id) if str(template_id or "").isdigit() else None
                ),
                "account_label": field("whatsapp_account").verbose_name,
                "template_label": field("whatsapp_template").verbose_name,
            },
            request=request,
        )
        response.content = response.content + html.encode()
        return response
