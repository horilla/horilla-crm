"""Miscellaneous template tags."""

from django.utils.encoding import force_str
from django.utils.safestring import mark_safe

# First party imports (Horilla)
from horilla.auth.models import User
from horilla.contrib.utils.methods import sanitize_html as _sanitize_html
from horilla.utils.translation import gettext as _

# Local imports
from ...forms.rich_text import HorillaSummernoteWidget
from ._registry import register


@register.filter(is_safe=True)
def sanitize_html(value):
    """Sanitize stored rich text before it is rendered as trusted HTML."""
    return mark_safe(_sanitize_html(value or ""))


@register.simple_tag
def empty_add_message(model_verbose_name):
    """Complete empty-state sentence with the translated model name interpolated."""
    return _("Nothing to show yet. Please add your %(model)s.") % {
        "model": force_str(model_verbose_name)
    }


@register.simple_tag
def get_user_model_meta():
    """
    Get the User model metadata
    Returns: dict with app_label, model_name, and model_name_original
    """
    return {
        "app_label": User._meta.app_label,
        "model_name": User._meta.model_name,
        "model_class_name": User.__name__,
    }


@register.simple_tag
def rich_text_editor(
    name, value="", preset="full", field_id=None, height="300px", filter_codeview=False
):
    """
    Render the shared Summernote editor for a plain (non-Django-form) page.

    The textarea is submitted as ``name`` and gets ``field_id`` (default
    ``id_<name>``), so ``hx-include="#<field_id>"`` picks up its value.
    ``filter_codeview`` strips script-like tags typed in the code view.
    """
    settings = {"height": height}
    if filter_codeview:
        # Block script-like tags typed in the code view
        settings.update(
            codeviewFilter=True,
            codeviewIframeFilter=True,
            codeviewFilterRegexSource=r"</*(?:script|iframe|object|embed|applet|svg|link)[^>]*>",
        )
    widget = HorillaSummernoteWidget(preset=preset, settings=settings)
    return widget.render(name, value or "", attrs={"id": field_id or f"id_{name}"})
