"""
Add WhatsApp to the Activity tab's side menu (next to Tasks, Meetings, Call,
Email and Events) through ViewExtension (_inherit_view), targeting the Activity
section view, the same way the Cadence app adds its detail tab. Nothing in the
Activity app is WhatsApp-specific.

The tab only appears for models that have a registered WhatsApp tab (see
registration.py) and for records that have a phone number.
"""

# First-party (Horilla)
from horilla.extension.view import ViewExtension
from horilla.urls import reverse
from horilla.utils.translation import gettext_lazy as _

_registered_tab_check_cache = {}


def _model_has_registered_whatsapp_tab(model):
    """Return True if register_whatsapp_tab() has wired a tab url for this model."""
    if model in _registered_tab_check_cache:
        return _registered_tab_check_cache[model]

    from .registration import whatsapp_tab_url_name

    try:
        reverse(whatsapp_tab_url_name(model), kwargs={"pk": 0})
        result = True
    except Exception:  # pylint: disable=broad-except
        result = False
    _registered_tab_check_cache[model] = result
    return result


def _record_has_phone_number(record):
    """Return True if the record has a non-empty value in any phone-like field."""
    from .registration import _phone_field_names

    return any(getattr(record, name, None) for name in _phone_field_names())


class ActivityWhatsAppTabExtension(ViewExtension):
    """Append the WhatsApp tab to the Activity tab's side menu when applicable."""

    _inherit_view = "horilla.contrib.activity.views.core.HorillaActivitySectionView"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        model = getattr(self, "model", None)
        record = getattr(self, "object", None)
        if (
            model is not None
            and record is not None
            and _model_has_registered_whatsapp_tab(model)
            and _record_has_phone_number(record)
        ):
            from .registration import whatsapp_tab_url_name

            context["extra_tabs"].append(
                {
                    "id": "whatsapp",
                    "title": _("WhatsApp"),
                    "url": reverse(
                        whatsapp_tab_url_name(model), kwargs={"pk": record.pk}
                    ),
                    "icon_template": "whatsapp_inbox/activity_tab_icon.html",
                }
            )
        return context
