"""
URLs for the form layouts settings page.
"""

# First party imports (Horilla)
from horilla.urls import path

# Local imports
from . import views

app_name = "form_layouts"

urlpatterns = [
    path(
        "",
        views.FormLayoutView.as_view(),
        name="form_layout_view",
    ),
    path(
        "editor/",
        views.FormLayoutEditorView.as_view(),
        name="form_layout_editor",
    ),
    path(
        "save/",
        views.FormLayoutSaveView.as_view(),
        name="form_layout_save",
    ),
    path(
        "reset/",
        views.FormLayoutResetView.as_view(),
        name="form_layout_reset",
    ),
]
