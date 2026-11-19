"""
URLs for the tour app
"""

# First party imports (Horilla)
from horilla.urls import path

# Local imports
from . import views

app_name = "tour"

urlpatterns = [
    path("", views.TourPanelView.as_view(), name="panel"),
    path("current/", views.TourCurrentView.as_view(), name="current"),
    path(
        "definition/<slug:key>/",
        views.TourDefinitionView.as_view(),
        name="definition",
    ),
    path("seen/", views.TourSeenView.as_view(), name="seen"),
]
