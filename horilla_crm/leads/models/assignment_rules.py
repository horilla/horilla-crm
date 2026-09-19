"""
Models for lead assignment rules, which define the criteria and logic for automatically
assigning leads to users or teams in the CRM system.
"""

# Third-party imports (Django)
from django.conf import settings

from horilla.contrib.core.models import HorillaCoreModel, Role
from horilla.contrib.mail.models import HorillaMailConfiguration, HorillaMailTemplate
from horilla.contrib.notifications.models import NotificationTemplate
from horilla.contrib.utils.methods import render_template

# First party imports (Horilla)
from horilla.core.exceptions import ValidationError
from horilla.db import models
from horilla.registry.permission_registry import permission_exempt_model
from horilla.urls import reverse_lazy
from horilla.utils.choices import OPERATOR_CHOICES
from horilla.utils.translation import gettext_lazy as _

# Local imports
from horilla_crm.leads.models.base import Lead

NOTIFY_METHOD_CHOICES = [
    ("email", _("Notify as Email")),
    ("notification", _("Notify as Notification")),
    ("both", _("Both")),
]

ASSIGN_TO_CHOICES = [
    ("user", _("User")),
    ("role", _("Role")),
]


class LeadAssignmentRule(HorillaCoreModel):
    """
    Top-level assignment rule container. Conditions are added from the detail view.
    is_active is inherited from HorillaCoreModel.
    """

    name = models.CharField(max_length=256, verbose_name=_("Rule Name"))
    description = models.TextField(blank=True, verbose_name=_("Description"))

    class Meta:
        """
        Meta options for LeadAssignmentRule. Specifies verbose names and default ordering.
        """

        verbose_name = _("Lead Assignment Rule")
        verbose_name_plural = _("Lead Assignment Rules")
        ordering = ["created_at"]

    def __str__(self):
        """
        Return the string representation of the LeadAssignmentRule, which is its name. Used in admin and other displays.
        """
        return str(self.name)

    def is_active_col(self):
        """
        Custom method to render the "is_active" column in the admin list view with a toggle switch.
        """
        return render_template(
            path="components/toggle_active_col.html",
            context={
                "instance": self,
                "toggle_url": reverse_lazy(
                    "leads:assignment_rule_activate", kwargs={"pk": self.pk}
                ),
            },
        )

    def get_edit_url(self):
        """
        Return the URL for editing this LeadAssignmentRule instance. Used in templates and views to link to the update page.
        """
        return reverse_lazy("leads:lead_assignment_update", kwargs={"pk": self.pk})

    def get_delete_url(self):
        """
        Return the URL for deleting this LeadAssignmentRule instance. Used in templates and views to link to the delete confirmation page.
        """
        return reverse_lazy("leads:lead_assignment_delete", kwargs={"pk": self.pk})

    def get_detail_url(self):
        """
        Return the URL for viewing the details of this LeadAssignmentRule instance. Used in templates and views to link to the detail page.
        """
        return reverse_lazy("leads:assignment_rule_detail", kwargs={"pk": self.pk})


@permission_exempt_model
class LeadAssignmentCondition(HorillaCoreModel):
    """
    A single condition row within an assignment rule.

    Each row defines:
      - the matching criteria (via related LeadAssignmentMatchCriteria rows)
      - the assignment target (user or role)
      - the notification method and templates

    Rows are evaluated in creation order; the first matching row wins.
    """

    rule = models.ForeignKey(
        LeadAssignmentRule,
        on_delete=models.CASCADE,
        related_name="conditions",
        verbose_name=_("Assignment Rule"),
    )

    # Assignment target
    assign_to_type = models.CharField(
        max_length=10,
        choices=ASSIGN_TO_CHOICES,
        default="user",
        verbose_name=_("Assign To"),
    )
    assign_to_users = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        blank=True,
        related_name="lead_assignment_conditions",
        verbose_name=_("Assign To Users"),
    )
    assign_to_roles = models.ManyToManyField(
        Role,
        blank=True,
        related_name="lead_assignment_conditions",
        verbose_name=_("Assign To Roles"),
    )

    # Notification
    notify_method = models.CharField(
        max_length=12,
        choices=NOTIFY_METHOD_CHOICES,
        blank=True,
        verbose_name=_("Notify Method"),
    )
    mail_template = models.ForeignKey(
        HorillaMailTemplate,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="lead_assignment_conditions",
        verbose_name=_("Mail Template"),
    )
    notification_template = models.ForeignKey(
        NotificationTemplate,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="lead_assignment_conditions",
        verbose_name=_("Notification Template"),
    )

    class Meta:
        """
        Meta options for LeadAssignmentCondition. Specifies verbose names and default ordering.
        """

        verbose_name = _("Lead Assignment Condition")
        verbose_name_plural = _("Lead Assignment Conditions")
        ordering = ["created_at"]

    def __str__(self):
        return f"{self.rule.name} — condition"

    def get_edit_url(self):
        """
        Return the URL for editing this LeadAssignmentCondition instance. Used in templates and views to link to the update page.
        """
        return reverse_lazy("leads:assignment_condition_update", kwargs={"pk": self.pk})

    def clean(self):
        """
        Custom validation to ensure that if a notification method is selected, the corresponding template is also provided. Raises ValidationError if the required template is missing based on the selected notify_method.
        """

        super().clean()
        if self.notify_method in ("email", "both"):
            if not self.mail_template_id:
                raise ValidationError(
                    {
                        "mail_template": _(
                            "Mail template is required for email notification."
                        )
                    }
                )
            if not HorillaMailConfiguration.objects.filter(
                mail_channel="outgoing"
            ).exists():
                raise ValidationError(
                    {
                        "notify_method": _(
                            "No outgoing mail configuration is set up. "
                            "Please configure a mail server before enabling "
                            "email notification."
                        )
                    }
                )
        if (
            self.notify_method in ("notification", "both")
            and not self.notification_template_id
        ):
            raise ValidationError(
                {
                    "notification_template": _(
                        "Notification template is required for in-app notification."
                    )
                }
            )


@permission_exempt_model
class LeadAssignmentMatchCriteria(HorillaCoreModel):
    """
    An individual matching criterion row within a LeadAssignmentCondition.

    Multiple rows can be linked to one condition using AND / OR logic.
    """

    condition = models.ForeignKey(
        LeadAssignmentCondition,
        on_delete=models.CASCADE,
        related_name="criteria",
        verbose_name=_("Assignment Condition"),
    )
    field = models.CharField(max_length=100, verbose_name=_("Field"))
    operator = models.CharField(
        max_length=50,
        choices=OPERATOR_CHOICES,
        verbose_name=_("Operator"),
    )
    value = models.CharField(max_length=255, blank=True, verbose_name=_("Value"))
    logical_operator = models.CharField(
        max_length=3,
        choices=[("and", _("AND")), ("or", _("OR"))],
        default="and",
        verbose_name=_("Logical Operator"),
    )

    class Meta:
        """Ordering and verbose names for criterion rows linked to assignment conditions."""

        verbose_name = _("Lead Assignment Match Criteria")
        verbose_name_plural = _("Lead Assignment Match Criteria")
        ordering = ["created_at"]

    def _get_custom_field_definition(self):
        """Resolve a 'cf_<id>' field to its CustomFieldDefinition, if any."""
        if not self.field.startswith("cf_"):
            return None
        try:
            from custom_fields.models import CustomFieldDefinition

            return CustomFieldDefinition.objects.filter(
                pk=self.field[len("cf_") :]
            ).first()
        except Exception:
            return None

    def get_field_label(self):
        """Return the verbose name of the Lead field (e.g. 'lead_status' → 'Lead Status'),
        or the custom field's own name for user-defined fields."""

        custom_field = self._get_custom_field_definition()
        if custom_field:
            return custom_field.name
        try:
            return Lead._meta.get_field(self.field).verbose_name
        except Exception:
            return self.field.replace("_", " ").title()

    def get_display_value(self):
        """Resolve FK PKs to their string representation for display."""

        if not self.value:
            return "-"
        if self.field.startswith("cf_"):
            return self.value
        try:
            meta_field = Lead._meta.get_field(self.field)
            related_model = getattr(meta_field, "related_model", None)
            if related_model:
                obj = related_model.objects.filter(pk=self.value).first()
                if obj:
                    return str(obj)
        except Exception:
            pass
        return self.value

    def __str__(self):
        """
        Return a string representation of the LeadAssignmentMatchCriteria, showing the field, operator, and value. Used in admin and other displays.
        """
        return f"{self.field} {self.operator} {self.value}"
