"""Shared rich text (Summernote) widget with named toolbar presets."""

# Third-party imports
from django_summernote.widgets import SummernoteInplaceWidget

TOOLBAR_PRESETS = {
    "full": [
        ["style", ["style"]],
        [
            "font",
            [
                "bold",
                "italic",
                "underline",
                "strikethrough",
                "superscript",
                "subscript",
                "clear",
            ],
        ],
        ["fontname", ["fontname"]],
        ["fontsize", ["fontsize"]],
        ["color", ["color"]],
        ["para", ["ul", "ol", "paragraph"]],
        ["height", ["height"]],
        ["table", ["table"]],
        ["insert", ["link", "picture", "video", "hr"]],
        ["view", ["fullscreen", "codeview"]],
        ["help", ["help"]],
    ],
    "chatter": [
        ["font", ["bold", "italic", "underline"]],
        ["para", ["ul", "ol"]],
        ["insert", ["link"]],
    ],
    "basic": [
        ["font", ["bold", "italic", "underline", "forecolor"]],
    ],
}


# Total editor height per preset. The widget's height includes the toolbar, so
# these leave roughly 300px of writing area under the taller "full" toolbar.
PRESET_HEIGHTS = {"full": "400px", "basic": "350px", "chatter": "100px"}


class HorillaSummernoteWidget(SummernoteInplaceWidget):
    """
    Summernote editor for form fields, configured by a toolbar preset.

    ``preset`` is a key of ``TOOLBAR_PRESETS``; ``settings`` overrides any
    Summernote option. The textarea is marked ``data-richtext`` so the shared
    ``HorillaRichText`` JS helper can sync it and insert text into it.
    """

    def __init__(self, preset="full", settings=None, attrs=None):
        self.editor_settings = {
            "width": "100%",
            "height": PRESET_HEIGHTS[preset],
            "airMode": False,
            "dialogsInBody": True,
            "toolbar": TOOLBAR_PRESETS[preset],
            **(settings or {}),
        }
        super().__init__(attrs={**(attrs or {}), "data-richtext": "true"})

    def format_value(self, value):
        """
        Double-escape entities in saved HTML.

        The inplace widget copies the textarea text into the editor with
        ``.html()``, which would otherwise decode ``&lt;``/``&gt;`` that are
        part of the content.
        """
        value = super().format_value(value)
        if value:
            value = value.replace("&lt;", "&amp;lt;").replace("&gt;", "&amp;gt;")
        return value

    def summernote_settings(self):
        """Merge the preset settings over the project-wide Summernote config."""
        merged = super().summernote_settings()
        merged.update(self.editor_settings)
        return merged
