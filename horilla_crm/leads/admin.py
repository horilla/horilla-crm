"""Admin configuration for the leads app in Horilla CRM."""

# Third-party imports (Django)
# Third-party imports (other)
from auditlog.models import LogEntry
from django.contrib import admin

# Local imports
from .models import (
    EmailToLeadConfig,
    Lead,
    LeadAssignmentCondition,
    LeadAssignmentMatchCriteria,
    LeadAssignmentRule,
    LeadCaptureForm,
    LeadStatus,
)

admin.site.register(Lead)
admin.site.register(LeadStatus)
admin.site.unregister(LogEntry)
admin.site.register(EmailToLeadConfig)
admin.site.register(LeadCaptureForm)

admin.site.register(LeadAssignmentRule)
admin.site.register(LeadAssignmentMatchCriteria)


@admin.register(LeadAssignmentCondition)
class LeadAssignmentConditionAdmin(admin.ModelAdmin):
    """Admin for lead assignment conditions with M2M assignee widgets."""

    filter_horizontal = ("assign_to_users", "assign_to_roles")
    list_display = ("__str__", "assign_to_type", "assignment_method")
    readonly_fields = ("last_assigned_user",)


@admin.register(LogEntry)
class CustomLogEntryAdmin(admin.ModelAdmin):
    """Custom admin for LogEntry to display relevant fields."""

    list_display = ("object_repr", "content_type", "action", "actor", "timestamp")
    list_filter = ("content_type", "action", "actor", "timestamp")
    search_fields = ("object_repr", "changes", "actor__username")
