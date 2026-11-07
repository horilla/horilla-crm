"""
URLs for the automations app
"""

# First party imports (Horilla)
from horilla.urls import path

# Local imports
from . import views
from .load_automation import CreateSelectedAutomationsView, LoadAutomationModalView

app_name = "automations"

urlpatterns = [
    path(
        "automation-view/",
        views.HorillaAutomationView.as_view(),
        name="automation_view",
    ),
    path(
        "automation-navbar-view/",
        views.HorillaAutomationNavbar.as_view(),
        name="automation_navbar_view",
    ),
    path(
        "automation-list-view/",
        views.HorillaAutomationListView.as_view(),
        name="automation_list_view",
    ),
    path(
        "automation-create-view/",
        views.HorillaAutomationFormView.as_view(),
        name="automation_create_view",
    ),
    path(
        "automation-update-view/<int:pk>/",
        views.HorillaAutomationFormView.as_view(),
        name="automation_update_view",
    ),
    path(
        "automation-detail-view/<int:pk>/",
        views.HorillaAutomationDetailView.as_view(),
        name="automation_detail_view",
    ),
    path(
        "get-automation-field-choices/",
        views.AutomationFieldChoicesView.as_view(),
        name="get_automation_field_choices",
    ),
    path(
        "get-mail-to-choices/",
        views.MailToChoicesView.as_view(),
        name="get_mail_to_choices",
    ),
    path(
        "get-template-fields/",
        views.TemplateFieldsView.as_view(),
        name="get_template_fields",
    ),
    path(
        "automation-delete-view/<int:pk>/",
        views.HorillaAutomationDeleteView.as_view(),
        name="automation_delete_view",
    ),
    path(
        "load-automation/",
        LoadAutomationModalView.as_view(),
        name="load_automation",
    ),
    path(
        "create-selected-automations/",
        CreateSelectedAutomationsView.as_view(),
        name="create_selected_automations",
    ),
]
