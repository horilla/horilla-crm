""" "URL configuration for the  app."""

# First party imports (Horilla)
from horilla.urls import path

# Local imports
from . import views
from .google_calendar import views as gcal_views

app_name = "calendar"

urlpatterns = [
    # Define your URL patterns here
    path("calendar-view/", views.CalendarView.as_view(), name="calendar_view"),
    path(
        "calendar-save-preference/",
        views.SaveCalendarPreferencesView.as_view(),
        name="save_calendar_preferences",
    ),
    path(
        "calendar-events/",
        views.GetCalendarEventsView.as_view(),
        name="get_calendar_events",
    ),
    path(
        "activity-assignees/<int:pk>/",
        views.ActivityAssigneesView.as_view(),
        name="activity_assignees",
    ),
    path("mark-completed/", views.MarkCompletedView.as_view(), name="mark_completed"),
    path(
        "mark-unavailability/",
        views.UserAvailabilityFormView.as_view(),
        name="mark_unavailability",
    ),
    path(
        "update-mark-unavailability/<int:pk>/",
        views.UserAvailabilityFormView.as_view(),
        name="update_mark_unavailability",
    ),
    path(
        "delete-mark-availability/<int:pk>/",
        views.UserAvailabilityDeleteView.as_view(),
        name="delete_mark_unavailability",
    ),
    path(
        "custom-calendar-create/",
        views.CustomCalendarFormView.as_view(),
        name="custom_calendar_create",
    ),
    path(
        "custom-calendar-update/<int:pk>/",
        views.CustomCalendarFormView.as_view(),
        name="custom_calendar_update",
    ),
    path(
        "custom-calendar-delete/<int:pk>/",
        views.CustomCalendarDeleteView.as_view(),
        name="custom_calendar_delete",
    ),
    # Google Integration admin settings (Settings → Integrations)
    path(
        "google-integration/settings/",
        gcal_views.GoogleIntegrationSettingsView.as_view(),
        name="google_integration_settings",
    ),
    path(
        "google-integration/allowed-users/",
        gcal_views.GoogleAllowedUsersListView.as_view(),
        name="google_allowed_users_list",
    ),
    path(
        "google-integration/allowed-roles/",
        gcal_views.GoogleAllowedRolesListView.as_view(),
        name="google_allowed_roles_list",
    ),
    path(
        "google-integration/access-roles/",
        gcal_views.GoogleAccessRolesView.as_view(),
        name="google_access_roles",
    ),
    path(
        "google-integration/access-users/",
        gcal_views.GoogleAccessUsersView.as_view(),
        name="google_access_users",
    ),
    # Google Calendar integration
    path(
        "google-calendar/settings/",
        gcal_views.GoogleCalendarSettingsView.as_view(),
        name="google_calendar_settings",
    ),
    path(
        "google-calendar/authorize/",
        gcal_views.GoogleCalendarAuthorizeView.as_view(),
        name="google_calendar_authorize",
    ),
    path(
        "google-calendar/callback/",
        gcal_views.GoogleCalendarCallbackView.as_view(),
        name="google_calendar_callback",
    ),
    path(
        "google-calendar/disconnect/",
        gcal_views.GoogleCalendarDisconnectView.as_view(),
        name="google_calendar_disconnect",
    ),
    path(
        "google-calendar/register-webhook/",
        gcal_views.GoogleCalendarRegisterWebhookView.as_view(),
        name="google_calendar_register_webhook",
    ),
    path(
        "google-calendar/sync-direction/",
        gcal_views.GoogleCalendarSyncDirectionView.as_view(),
        name="google_calendar_sync_direction",
    ),
    # Google Calendar push-notification webhook (called by Google, not users)
    path(
        "webhook/google/",
        gcal_views.GoogleCalendarWebhookView.as_view(),
        name="google_calendar_webhook",
    ),
]
