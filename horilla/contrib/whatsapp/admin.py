"""
Admin registration for the whatsapp app
"""

# Third-party imports (Django)
from django.contrib import admin

# Local imports
from .models import (
    WhatsAppAccount,
    WhatsAppAttachment,
    WhatsAppBotRule,
    WhatsAppBotRuleEdge,
    WhatsAppBotRuleNode,
    WhatsAppBotRuleSession,
    WhatsAppConversation,
    WhatsAppFlow,
    WhatsAppMessage,
    WhatsAppScheduledResume,
    WhatsAppTemplate,
)

admin.site.register(WhatsAppAccount)
admin.site.register(WhatsAppConversation)
admin.site.register(WhatsAppMessage)
admin.site.register(WhatsAppAttachment)
admin.site.register(WhatsAppTemplate)
admin.site.register(WhatsAppFlow)


@admin.register(WhatsAppBotRule)
class WhatsAppBotRuleAdmin(admin.ModelAdmin):
    """Admin for WhatsAppBotRule."""

    list_display = ("name", "account", "trigger_type", "is_active", "version")


@admin.register(WhatsAppBotRuleSession)
class WhatsAppBotRuleSessionAdmin(admin.ModelAdmin):
    """Admin for WhatsAppBotRuleSession."""

    list_display = ("flow", "conversation", "status", "current_node_key", "updated_at")


admin.site.register(WhatsAppBotRuleNode)
admin.site.register(WhatsAppBotRuleEdge)
admin.site.register(WhatsAppScheduledResume)
