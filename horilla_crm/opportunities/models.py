"""
Opportunities module models.
"""

# Third-party imports (Django)
from django.core.validators import EmailValidator, MaxValueValidator, MinValueValidator
from django.dispatch import receiver

# First party imports (Horilla)
from horilla import settings
from horilla.contrib.core.models import (
    Company,
    CustomerRole,
    HorillaCoreModel,
    TeamRole,
)
from horilla.contrib.utils.methods import render_template
from horilla.contrib.utils.middlewares import _thread_local
from horilla.core.exceptions import ValidationError
from horilla.db import models, transaction
from horilla.db.models.signals import post_delete, pre_save
from horilla.registry.permission_registry import permission_exempt_model
from horilla.urls import reverse_lazy
from horilla.utils.translation import gettext_lazy as _

# Local imports
from horilla_crm.accounts.models import Account
from horilla_crm.campaigns.models import Campaign
from horilla_crm.contacts.models import Contact
from horilla_crm.scoring_rules.utils import compute_score

DEFAULT_OPPORTUNITY_INIT_STAGES = (
    {"name": _("Prospecting"), "order": 1, "probability": 10, "is_final": False},
    {"name": _("Qualification"), "order": 2, "probability": 20, "is_final": False},
    {"name": _("Needs Analysis"), "order": 3, "probability": 30, "is_final": False},
    {"name": _("Value Proposition"), "order": 4, "probability": 50, "is_final": False},
    {
        "name": _("Id. Decision Makers"),
        "order": 5,
        "probability": 60,
        "is_final": False,
    },
    {
        "name": _("Perception Analysis"),
        "order": 6,
        "probability": 70,
        "is_final": False,
    },
    {
        "name": _("Proposal/Price Quote"),
        "order": 7,
        "probability": 80,
        "is_final": False,
    },
    {"name": _("Negotiation/Review"), "order": 8, "probability": 90, "is_final": False},
    {"name": _("Closed Lost"), "order": 9, "probability": 0, "is_final": False},
    {"name": _("Closed Won"), "order": 10, "probability": 100, "is_final": True},
)


class OpportunityStage(HorillaCoreModel):
    """Opportunity Stage model for flexible stage management"""

    STAGE_TYPE_CHOICES = [
        ("open", _("Open")),
        ("won", _("Closed Won")),
        ("lost", _("Closed Lost")),
    ]

    name = models.CharField(max_length=100, verbose_name=_("Stage Name"))
    order = models.PositiveIntegerField(
        verbose_name=_("Order"), help_text="Order in which stages appear"
    )
    probability = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        verbose_name=_("Probability"),
        help_text=_("Default probability percentage for this stage"),
    )
    is_final = models.BooleanField(
        default=False, db_index=True, verbose_name=_("Is Final Stage")
    )
    stage_type = models.CharField(
        max_length=10,
        choices=STAGE_TYPE_CHOICES,
        default="open",
        db_index=True,
        verbose_name=_("Stage Type"),
        help_text=_("Type of stage - Open, Closed Won, or Closed Lost"),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._desired_position = None

    def is_final_col(self):
        """Returns the HTML for the is_final column in the list view."""
        html = render_template(
            path="opportunity_stage/is_final_col.html",
            context={"instance": self},
        )
        return html

    def clean(self):
        """Validate that opportunity stage order is non-negative."""
        if self.order is not None and self.order < 0:
            raise ValidationError(_("Order must be a non-negative integer."))

    @property
    def is_won(self):
        """Helper property to check if this is a won stage"""
        return self.stage_type == "won"

    @property
    def is_lost(self):
        """Helper property to check if this is a lost stage"""
        return self.stage_type == "lost"

    @property
    def is_closed(self):
        """Helper property to check if this is any closed stage"""
        return self.stage_type in ["won", "lost"]

    def save(self, *args, **kwargs):
        with transaction.atomic():
            previous_final = None
            if self.is_final:
                previous_final = (
                    OpportunityStage.objects.filter(is_final=True, company=self.company)
                    .exclude(pk=self.pk)
                    .first()
                )
                if previous_final:
                    OpportunityStage.objects.filter(pk=previous_final.pk).update(
                        is_final=False
                    )

            if self.pk is None:
                # For new stages, use provided order or next available order
                desired_order = self.order
                if not self.order:
                    self.order = self.get_next_order_for_company(self.company)
                    desired_order = self.order
                else:
                    # Check if the provided order already exists for this company
                    if OpportunityStage.objects.filter(
                        company=self.company, order=self.order
                    ).exists():
                        # If order conflicts, use a temporary high value to avoid constraint violation
                        # The _reorder_all_statuses method will handle proper ordering
                        # Find a safe temporary value that won't conflict
                        max_order = OpportunityStage.objects.filter(
                            company=self.company
                        ).aggregate(max_order=models.Max("order"))["max_order"]
                        # Use a value that's guaranteed to be unique (higher than max + large offset)
                        # and higher than reordering temp values (10000+)
                        self.order = max((max_order or 0) + 50000, 100000)
                    else:
                        desired_order = self.order
                self._desired_position = desired_order if not self.is_final else None
            else:
                original = OpportunityStage.objects.get(pk=self.pk)
                is_final_changed = self.is_final != original.is_final

                if is_final_changed or self.order != original.order:
                    self._desired_position = self.order if not self.is_final else None

            super().save(*args, **kwargs)
            self._reorder_all_statuses(previous_final=previous_final)

    def _reorder_all_statuses(self, previous_final=None):
        """
        Reorder all statuses for the company to ensure sequential ordering with final stage last.
        Uses temporary order numbers to avoid unique constraint violations.
        """
        company_statuses = list(
            OpportunityStage.objects.filter(company=self.company)
            .select_for_update()
            .order_by("order", "pk")
        )

        final_statuses = [s for s in company_statuses if s.is_final]
        non_final_statuses = [s for s in company_statuses if not s.is_final]

        if len(final_statuses) > 1:
            if self.is_final and self in final_statuses:
                final_statuses = [self]
            else:
                final_statuses = final_statuses[:1]
            for status in [
                s for s in company_statuses if s.is_final and s not in final_statuses
            ]:
                OpportunityStage.objects.filter(pk=status.pk).update(is_final=False)

        if hasattr(self, "_desired_position") and self._desired_position is not None:
            desired_order = self._desired_position
            non_final_statuses = [s for s in non_final_statuses if s != self]
            non_final_statuses.sort(key=lambda x: x.order)

            max_order = max((s.order for s in non_final_statuses), default=0)

            if desired_order > max_order:
                non_final_statuses.append(self)
            else:
                non_final_statuses.insert(max(0, desired_order - 1), self)
        else:
            non_final_statuses.sort(key=lambda x: x.order)

        if previous_final and previous_final in non_final_statuses:
            non_final_statuses.remove(previous_final)
            reordered_statuses = non_final_statuses + [previous_final] + final_statuses
        else:
            reordered_statuses = non_final_statuses + final_statuses

        temp_order_start = 10000
        for idx, status in enumerate(reordered_statuses):
            OpportunityStage.objects.filter(pk=status.pk).update(
                order=temp_order_start + idx
            )

        for i, status in enumerate(reordered_statuses, 1):
            OpportunityStage.objects.filter(pk=status.pk).update(order=i)

        if hasattr(self, "_desired_position"):
            delattr(self, "_desired_position")

    @staticmethod
    @receiver(post_delete, sender="opportunities.OpportunityStage")
    def handle_bulk_delete(sender, instance, **kwargs):
        """
        Handle bulk deletions or queryset deletions by reordering remaining statuses
        and setting the last stage as final if no final stage exists.
        """
        with transaction.atomic():
            try:
                company = instance.company  # Attempt to access the company
                # Ensure the company exists in the database
                if not Company.objects.filter(pk=company.pk).exists():
                    return
                was_final = instance.is_final
                remaining_statuses = list(
                    OpportunityStage.objects.filter(company=company).order_by("order")
                )
                for i, status in enumerate(remaining_statuses, 1):
                    OpportunityStage.objects.filter(pk=status.pk).update(order=i)
                if (
                    was_final
                    and remaining_statuses
                    and not any(s.is_final for s in remaining_statuses)
                ):
                    last_stage = remaining_statuses[-1]
                    OpportunityStage.objects.filter(pk=last_stage.pk).update(
                        is_final=True
                    )
            except Company.DoesNotExist:
                return

    @classmethod
    def get_next_order_for_company(cls, company):
        """
        Get the next available order number for a company, just before final stage
        """
        max_order = cls.objects.filter(company=company, is_final=False).aggregate(
            max_order=models.Max("order")
        )["max_order"]
        return (max_order or 0) + 1

    def get_edit_url(self):
        """
        This method to get edit url
        """
        return reverse_lazy(
            "opportunities:edit_opportunity_stage", kwargs={"pk": self.pk}
        )

    def get_delete_url(self):
        """
        This method to get delete url
        """
        return reverse_lazy(
            "opportunities:delete_opportunity_stage", kwargs={"pk": self.pk}
        )

    class Meta:
        """Meta options for OpportunityStage model."""

        verbose_name = _("Opportunity Stage")
        verbose_name_plural = _("Opportunity Stages")
        ordering = ["order"]
        constraints = [
            models.UniqueConstraint(
                fields=["name", "company"], name="unique_stage_name_per_company"
            ),
            models.UniqueConstraint(
                fields=["order", "company"], name="unique_stage_order_per_company"
            ),
        ]

    def __str__(self):
        return str(self.name)


class Opportunity(HorillaCoreModel):
    """Django model based on  Opportunity object"""

    TYPE_CHOICES = [
        ("existing_customer_upgrade", _("Existing Customer - Upgrade")),
        ("existing_customer_replacement", _("Existing Customer - Replacement")),
        ("existing_customer_downgrade", _("Existing Customer - Downgrade")),
        ("new_customer", _("New Customer")),
    ]

    LEAD_SOURCES = [
        ("website", _("Website")),
        ("referral", _("Referral")),
        ("event", _("Event")),
        ("campaign", _("Campaign")),
        ("phone", _("Phone")),
        ("email", _("Email")),
        ("social media", _("Social Media")),
        ("partner", _("Partner")),
        ("other", _("Other")),
    ]

    FORECAST_CATEGORY_CHOICES = [
        ("omitted", _("Omitted")),
        ("pipeline", _("Pipeline")),
        ("best_case", _("Best Case")),
        ("commit", _("Commit")),
        ("closed", _("Closed")),
    ]

    DELIVERY_STATUS_CHOICES = [
        ("yet_to_fulfill", _("Yet to Fulfill")),
        ("partially_delivered", _("Partially Delivered")),
        ("completely_delivered", _("Completely Delivered")),
    ]

    name = models.CharField(max_length=120, verbose_name=_("Opportunity Name"))
    email = models.EmailField(
        validators=[EmailValidator()], verbose_name=_("Email"), null=True, blank=True
    )

    amount = models.DecimalField(
        max_digits=18, decimal_places=2, null=True, blank=True, verbose_name=_("Amount")
    )
    expected_revenue = models.DecimalField(
        max_digits=18,
        decimal_places=2,
        null=True,
        blank=True,
        verbose_name=_("Expected Revenue"),
    )
    quantity = models.DecimalField(
        max_digits=16,
        decimal_places=2,
        null=True,
        blank=True,
        verbose_name=_("Quantity"),
        help_text=_("Total Opportunity Quantity"),
    )
    close_date = models.DateField(
        null=True, blank=True, db_index=True, verbose_name=_("Close Date")
    )
    stage = models.ForeignKey(
        OpportunityStage,
        on_delete=models.PROTECT,
        verbose_name=_("Stage"),
    )
    probability = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        null=True,
        blank=True,
        verbose_name=_("Probability"),
        help_text=_("Probability percentage (0-100)"),
        validators=[MinValueValidator(0), MaxValueValidator(100)],
    )
    description = models.TextField(
        max_length=32000, blank=True, verbose_name=_("Description")
    )
    next_step = models.CharField(
        max_length=255, blank=True, verbose_name=_("Next Step")
    )
    opportunity_score = models.IntegerField(
        default=0, verbose_name=_("Opportunity Score")
    )
    primary_campaign_source = models.ForeignKey(
        Campaign,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        verbose_name=_("Primary Campaign Source"),
        related_name="opportunities",
    )
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        verbose_name=_("Owner"),
        help_text=_("Opportunity Owner"),
    )
    opportunity_type = models.CharField(
        max_length=50, choices=TYPE_CHOICES, blank=True, verbose_name=_("Type")
    )
    lead_source = models.CharField(
        max_length=50, choices=LEAD_SOURCES, blank=True, verbose_name=_("Lead Source")
    )
    forecast_category = models.CharField(
        max_length=50,
        choices=FORECAST_CATEGORY_CHOICES,
        blank=True,
        db_index=True,
        verbose_name=_("Forecast Category"),
    )
    delivery_installation_status = models.CharField(
        max_length=50,
        choices=DELIVERY_STATUS_CHOICES,
        blank=True,
        verbose_name=_("Delivery Installation Status"),
    )
    main_competitors = models.CharField(
        max_length=100, blank=True, verbose_name=_("Main Competitors")
    )
    order_number = models.CharField(
        max_length=8, blank=True, verbose_name=_("Order Number")
    )
    tracking_number = models.CharField(
        max_length=12, blank=True, verbose_name=_("Tracking Number")
    )
    account = models.ForeignKey(
        Account,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        verbose_name=_("Account"),
        related_name="opportunity_account",
    )

    OWNER_FIELDS = ["owner"]
    CURRENCY_FIELDS = ["amount", "expected_revenue"]
    # Offered in the "Send to" picker of mail and phone channels (Automations,
    # Workflow, Cadences) as "Primary Contact - <field>".
    RECIPIENT_RELATIONS = {
        "primary_contact": ("contacts.Contact", _("Primary Contact")),
    }
    # Reverse relations whose rows must not be merged into the History tab.
    FULL_HISTORY_EXCLUDE = ["converted_from_leads"]

    def get_history_sources(self):
        """Converted leads whose activities, notes and emails also show here."""
        return list(self.converted_from_leads.all())

    # opportunity_access levels that grant each action, via OpportunityTeamMember.
    TEAM_ACCESS_LEVELS_FOR_ACTION = {
        "view": ["read", "edit", "owner"],
        "change": ["edit", "owner"],
        "delete": ["edit", "owner"],
    }

    class Meta:
        """Meta options for Opportunity model."""

        verbose_name = _("Opportunity")
        verbose_name_plural = _("Opportunities")
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.name}"

    @property
    def primary_contact(self):
        """
        The contact of the opportunity's active primary contact role, or
        ``None``. With several primary roles, the one added first. Read
        without the active-company filter, as Workflow and Cadences also send
        from Celery, where no company is active.
        """
        if not self.pk:
            return None
        role = (
            OpportunityContactRole.all_objects.filter(
                opportunity_id=self.pk,
                is_primary=True,
                is_active=True,
                contact__is_active=True,
            )
            .select_related("contact")
            .order_by("pk")
            .first()
        )
        return role.contact if role else None

    @classmethod
    def granted_access_filter(cls, user, action):
        """
        Q object matching Opportunities where ``user`` is an OpportunityTeamMember
        whose opportunity_access grants ``action`` ("view", "change", "delete").
        """
        levels = cls.TEAM_ACCESS_LEVELS_FOR_ACTION.get(action)
        if not levels:
            return models.Q(pk__in=[])
        return models.Q(
            opportunity_team_members__user=user,
            opportunity_team_members__opportunity_access__in=levels,
        )

    def has_granted_access(self, user, action):
        """
        True if ``user`` is an OpportunityTeamMember of this opportunity whose
        opportunity_access grants ``action`` ("view", "change", "delete").
        """
        levels = self.TEAM_ACCESS_LEVELS_FOR_ACTION.get(action)
        if not levels:
            return False
        return self.opportunity_team_members.filter(
            user=user, opportunity_access__in=levels
        ).exists()

    def _is_owner(self, user):
        """True if ``user`` is the record owner or a subordinate of the owner's role."""
        from horilla.contrib.core.utils import get_allowed_user_ids

        return self.owner_id in get_allowed_user_ids(user)

    def is_view_granted(self, user):
        """owner_method hook for list-view actions requiring view-level access."""
        return self._is_owner(user) or self.has_granted_access(user, "view")

    def is_change_granted(self, user):
        """owner_method hook for list-view actions requiring change-level access."""
        return self._is_owner(user) or self.has_granted_access(user, "change")

    def is_delete_granted(self, user):
        """owner_method hook for list-view actions requiring delete-level access."""
        return self._is_owner(user) or self.has_granted_access(user, "delete")

    DYNAMIC_METHODS = ["get_change_owner_url", "get_edit_url", "get_detail_url"]

    def get_link_leads_url(self):
        """
        This method to get the url that links converted leads to this opportunity
        """
        return reverse_lazy("leads:link_leads_to_opportunity", kwargs={"pk": self.pk})

    def get_change_owner_url(self):
        """
        This method to get edit url
        """
        return reverse_lazy(
            "opportunities:opportunity_change_owner", kwargs={"pk": self.pk}
        )

    def get_edit_url(self):
        """
        This method to get edit url
        """
        return reverse_lazy(
            "opportunities:opportunity_single_edit", kwargs={"pk": self.pk}
        )

    def get_duplicate_url(self):
        """
        This method to get edit url
        """
        return reverse_lazy(
            "opportunities:opportunity_single_edit", kwargs={"pk": self.pk}
        )

    def get_delete_url(self):
        """
        This method to get delete url
        """
        return reverse_lazy("opportunities:opportunity_delete", kwargs={"pk": self.pk})

    def get_detail_url(self):
        """
        This method to get delete url
        """
        return reverse_lazy(
            "opportunities:opportunity_detail_view", kwargs={"pk": self.pk}
        )

    def set_forecast_category(self):
        """
        Set forecast_category based on the stage's probability and status.
        """
        if not self.stage:
            self.forecast_category = "pipeline"
            return

        # If stage is lost, set to omitted
        if self.stage.is_lost:
            self.forecast_category = "omitted"

        # If stage is won, set to closed
        elif self.stage.is_won:
            self.forecast_category = "closed"

        # Otherwise, map probability to forecast category
        else:
            probability = self.probability or self.stage.probability or 0
            if probability < 10:
                self.forecast_category = "pipeline"
            elif 10 <= probability <= 40:
                self.forecast_category = "pipeline"
            elif 41 <= probability <= 70:
                self.forecast_category = "best_case"
            elif 71 <= probability <= 99:
                self.forecast_category = "commit"
            elif probability == 100:
                self.forecast_category = "closed"

    def save(self, *args, **kwargs):
        if self.stage:
            self.probability = self.stage.probability
        if self.amount is not None and self.probability is not None:
            self.expected_revenue = self.amount * (self.probability / 100)
        self.set_forecast_category()

        super().save(*args, **kwargs)


@receiver(pre_save, sender=Opportunity)
def update_opportunity_score(sender, instance, **kwargs):
    """
    Computes and updates the opportunity score before saving the Opportunity instance.
    """
    instance.opportunity_score = compute_score(instance)


class OpportunityContactRole(HorillaCoreModel):
    """Links a contact to an opportunity with a specific role."""

    contact = models.ForeignKey(
        Contact,
        on_delete=models.CASCADE,
        related_name="opportunity_roles",
        verbose_name="Contact",
        null=False,
        blank=False,
    )

    opportunity = models.ForeignKey(
        Opportunity,
        on_delete=models.CASCADE,
        related_name="contact_roles",
        verbose_name="Opportunity",
        null=False,
        blank=False,
    )

    is_primary = models.BooleanField(default=False, verbose_name="Primary")

    role = models.ForeignKey(
        CustomerRole,
        on_delete=models.SET_NULL,
        related_name="opportunity_contact_roles",
        verbose_name=_("Customer Role"),
        null=True,
        blank=True,
    )

    def get_edit_url(self):
        """
        This method to get edit url
        """
        return reverse_lazy(
            "opportunities:edit_opportunity_contact_role", kwargs={"pk": self.pk}
        )

    def get_delete_url(self):
        """
        This method to get delete url
        """
        return reverse_lazy(
            "opportunities:opportunity_contact_role_delete", kwargs={"pk": self.pk}
        )

    class Meta:
        """Meta options for OpportunityContactRole model."""

        verbose_name = _("Opportunity Contact Role")
        verbose_name_plural = _("Opportunity Contact Roles")
        unique_together = ("contact", "opportunity")

    def __str__(self):
        return f"{self.contact} - {self.opportunity} ({self.role})"


ACCESS_LEVEL_CHOICES = [
    ("read", _("Read Only")),
    ("edit", _("Read/Write")),
    ("owner", _("Owner")),
]


class OpportunityTeam(HorillaCoreModel):
    """Represents a team assigned to manage opportunities."""

    team_name = models.CharField(max_length=255, verbose_name=_("Team Name"))
    description = models.TextField(blank=True, verbose_name=_("Description"))
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="owner",
        verbose_name=_("Owner"),
    )

    OWNER_FIELDS = ["owner"]

    class Meta:
        """Meta options for OpportunityTeam model."""

        verbose_name = _("Opportunity Team")
        verbose_name_plural = _("Opportunity Teams")

    def get_edit_url(self):
        """
        This method to get edit url
        """
        return reverse_lazy(
            "opportunities:edit_opportunity_team", kwargs={"pk": self.pk}
        )

    def get_detail_view_url(self):
        """
        This method to get detail view url
        """
        return reverse_lazy(
            "opportunities:opportunity_team_detail_view", kwargs={"pk": self.pk}
        )

    def get_delete_url(self):
        """
        This method to get delete url
        """
        return reverse_lazy(
            "opportunities:delete_opportunity_team", kwargs={"pk": self.pk}
        )

    def __str__(self):
        return str(self.team_name)


class OpportunityTeamMember(HorillaCoreModel):
    """Represents a member of an opportunity team with a specific role and access level."""

    opportunity = models.ForeignKey(
        "Opportunity",
        on_delete=models.CASCADE,
        related_name="opportunity_team_members",
        verbose_name=_("Opportunity"),
    )
    opportunity_access = models.CharField(
        max_length=255,
        choices=ACCESS_LEVEL_CHOICES,
        default="Read",
        verbose_name=_("Opportunity Access"),
    )
    team_role = models.ForeignKey(
        TeamRole,
        on_delete=models.CASCADE,
        related_name="default_team_role",
        verbose_name=_("Member Role"),
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="opportunty_team_users",
        verbose_name=_("Team Members"),
    )

    class Meta:
        """Meta options for OpportunityTeamMember model."""

        verbose_name = _("Opportunity Team Member")
        verbose_name_plural = _("Opportunity Team Members")

    def __str__(self):
        return f"{self.user} - {self.team_role}"

    def get_edit_url(self):
        """
        This method to get edit url
        """
        return reverse_lazy(
            "opportunities:edit_opportunity_member", kwargs={"pk": self.pk}
        )

    def get_delete_url(self):
        """
        This method to get delete url
        """
        return reverse_lazy(
            "opportunities:delete_opportunity_member", kwargs={"pk": self.pk}
        )


@permission_exempt_model
class DefaultOpportunityMember(HorillaCoreModel):
    """
    Default team members that get automatically added to new opportunities
    """

    team = models.ForeignKey(
        "OpportunityTeam",
        on_delete=models.CASCADE,
        related_name="team_members",
        verbose_name=_("Team Name"),
    )

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="default_opportunity_memberships",
        verbose_name=_("Team Member"),
    )

    team_role = models.ForeignKey(
        TeamRole,
        on_delete=models.CASCADE,
        related_name="team_role",
        verbose_name=_("Member Role"),
    )
    opportunity_access_level = models.CharField(
        choices=ACCESS_LEVEL_CHOICES, max_length=20, verbose_name=_("Access Level")
    )

    class Meta:
        """Meta options for DefaultOpportunityMember model."""

        verbose_name = _("Default Opportunity Member")
        verbose_name_plural = _("Default Opportunity Members")
        unique_together = ("user", "team")

    def get_edit_url(self):
        """
        This method to get edit url
        """
        return reverse_lazy(
            "opportunities:edit_opportunity_team_member", kwargs={"pk": self.pk}
        )

    def get_delete_url(self):
        """
        This method to get delete url
        """
        return reverse_lazy(
            "opportunities:delete_opportunity_team_member", kwargs={"pk": self.pk}
        )

    def __str__(self):
        return f"{self.user.get_full_name() or self.user.username}"


class OpportunitySettings(HorillaCoreModel):
    """
    Global settings for Opportunity module features
    """

    CACHE_NAMESPACE = "opportunities.settings"

    team_selling_enabled = models.BooleanField(
        default=False,
        verbose_name=_("Enable Team Selling"),
        help_text=_(
            "Enable Opportunity Teams to help multiple users collaborate on opportunities. "
            "When enabled, you can define roles for team members, set record-level access, "
            "and view teams in list views and reports."
        ),
    )

    team_selling_access_type = models.CharField(
        max_length=10,
        choices=[
            ("all", _("All Users")),
            ("roles", _("Specific Roles")),
            ("users", _("Specific Users")),
        ],
        default="all",
        verbose_name=_("Team Selling Access Type"),
        help_text=_("Who can use opportunity teams."),
    )
    team_selling_allowed_roles = models.ManyToManyField(
        "core.Role",
        blank=True,
        related_name="team_selling_settings",
        verbose_name=_("Team Selling Allowed Roles"),
    )
    team_selling_allowed_users = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        blank=True,
        related_name="team_selling_settings",
        verbose_name=_("Team Selling Allowed Users"),
    )

    split_enabled = models.BooleanField(
        default=False,
        verbose_name=_("Enable Opportunity Splits"),
        help_text=_(
            "Allow multiple users to share credit for an opportunity. "
            "Splits can be based on revenue, overlay, or custom metrics."
        ),
    )

    allow_all_users_in_splits = models.BooleanField(
        default=False,
        verbose_name=_(
            "Let Users Add Members to Opportunity Teams While Editing Splits"
        ),
        help_text=_(
            "When enabled, users can assign splits to any active user in the company, "
            "not just opportunity team members. This allows adding new members while editing splits."
        ),
    )

    class Meta:
        """Meta options for OpportunitySettings."""

        verbose_name = _("Opportunity Setting")
        verbose_name_plural = _("Opportunity Settings")
        unique_together = ("company",)

    def __str__(self):
        return str(_("Opportunity Settings"))

    @classmethod
    def get_settings(cls, company):
        """Get or create settings for the given company"""
        from horilla.contrib.utils.company_settings_cache import (
            invalidate_company_setting,
        )

        if not company:
            return None
        settings, created = cls.objects.get_or_create(
            company=company, defaults={"team_selling_enabled": False}
        )
        if created:
            invalidate_company_setting(cls.CACHE_NAMESPACE, company.pk)
        return settings

    @classmethod
    def _resolve_company(cls, company_or_request=None):
        """Resolve a Company from a request, a Company instance, or thread-local."""
        from rest_framework.request import Request as DRFRequest

        from horilla.web import HttpRequest

        if company_or_request is None or isinstance(
            company_or_request, (HttpRequest, DRFRequest)
        ):
            request = company_or_request or getattr(_thread_local, "request", None)
            if request is None:
                return None
            return getattr(request.user, "company", None)
        # Passed an actual Company object
        return company_or_request

    @classmethod
    def _get_cached_settings(cls, company_or_request=None):
        """
        Resolve the OpportunitySettings row for a company.

        Uses request-local cache then Django ``cache.get_or_set`` (per
        company) so menu / feature checks avoid a DB hit every request.
        """
        from rest_framework.request import Request as DRFRequest

        from horilla.contrib.utils.company_settings_cache import (
            get_or_set_company_setting,
        )
        from horilla.web import HttpRequest

        if isinstance(company_or_request, (HttpRequest, DRFRequest)):
            request = company_or_request
        else:
            request = getattr(_thread_local, "request", None)

        company = cls._resolve_company(company_or_request)
        if not company:
            return None

        company_id = company.pk
        cache_attr = "_opportunity_settings_cache"
        if request is not None:
            cached = getattr(request, cache_attr, None)
            if cached is None:
                cached = {}
                setattr(request, cache_attr, cached)
            if company_id in cached:
                return cached[company_id]

        setting = get_or_set_company_setting(
            cls.CACHE_NAMESPACE,
            company_id,
            lambda: cls.all_objects.filter(company_id=company_id).first(),
        )
        if request is not None:
            cached[company_id] = setting
        return setting

    @classmethod
    def is_team_selling_enabled(cls, company_or_request=None):
        """Quick check if team selling is enabled for a company"""
        settings = cls._get_cached_settings(company_or_request)
        return settings.team_selling_enabled if settings else False

    def user_has_team_selling_access(self, user):
        """Return True if ``user`` may use team selling under the access rules."""
        if not self.team_selling_enabled:
            return False
        if self.team_selling_access_type == "all":
            return True
        if self.team_selling_access_type == "roles":
            role_id = getattr(user, "role_id", None)
            return bool(
                role_id and self.team_selling_allowed_roles.filter(pk=role_id).exists()
            )
        if self.team_selling_access_type == "users":
            return self.team_selling_allowed_users.filter(pk=user.pk).exists()
        return False

    @classmethod
    def user_can_use_team_selling(cls, request=None):
        """Menu/view condition: team selling is enabled and the user is allowed."""
        if request is None:
            request = getattr(_thread_local, "request", None)
        user = getattr(request, "user", None)
        if not user or not user.is_authenticated:
            return False
        setting = cls._get_cached_settings(request)
        return bool(setting and setting.user_has_team_selling_access(user))

    @classmethod
    def is_split_enabled(cls, company_or_request=None):
        """Quick check if splits are enabled for a company"""
        settings = cls._get_cached_settings(company_or_request)
        return settings.split_enabled if settings else False

    @classmethod
    def allow_all_users_in_splits_enabled(cls, company_or_request=None):
        """Quick check if all users can be added in splits for a company"""
        settings = cls._get_cached_settings(company_or_request)
        return settings.allow_all_users_in_splits if settings else False

    def save(self, *args, **kwargs):
        """
        Override save to:
          - Keep Opportunity Splits consistent with Team Selling. Splits
            require Team Selling to be enabled, so turning Team Selling off
            automatically turns Splits (and "allow all users in splits")
            off too, and clears any existing split assignments.
          - Create default split types the first time Splits are enabled.
        """
        is_new = self.pk is None
        old_split_enabled = None
        old_team_selling_enabled = None

        if not is_new:
            try:
                old_instance = OpportunitySettings.objects.get(pk=self.pk)
                old_split_enabled = old_instance.split_enabled
                old_team_selling_enabled = old_instance.team_selling_enabled
            except OpportunitySettings.DoesNotExist:
                pass

        # Opportunity Splits depend on Team Selling. If Team Selling isn't
        # enabled, Splits (and the "allow all users" split option) can't be
        # enabled either.
        if not self.team_selling_enabled:
            self.split_enabled = False
            self.allow_all_users_in_splits = False

        super().save(*args, **kwargs)

        from horilla.contrib.utils.company_settings_cache import (
            invalidate_company_setting,
        )

        invalidate_company_setting(self.CACHE_NAMESPACE, self.company_id)

        # Create default split types when splits are enabled for the first time
        if self.split_enabled and (is_new or old_split_enabled is False):
            self._create_default_split_types()

        # Team Selling was just turned off while Splits were still enabled -
        # existing split assignments for this company are no longer valid.
        if (
            old_team_selling_enabled
            and not self.team_selling_enabled
            and old_split_enabled
        ):
            OpportunitySplit.objects.filter(opportunity__company=self.company).delete()

    def delete(self, *args, **kwargs):
        """Delete and drop the per-company Django cache entry."""
        from horilla.contrib.utils.company_settings_cache import (
            invalidate_company_setting,
        )

        company_id = self.company_id
        super().delete(*args, **kwargs)
        invalidate_company_setting(self.CACHE_NAMESPACE, company_id)

    def _create_default_split_types(self):
        """Create Revenue and Overlay split types"""
        OpportunitySplitType.objects.get_or_create(
            company=self.company,
            split_label=_("Expected Revenue Overlay"),
            defaults={
                "split_field": "expected_revenue",
                "totals_100_percent": False,
                "is_active": False,
            },
        )
        OpportunitySplitType.objects.get_or_create(
            company=self.company,
            split_label=_("Expected Revenue"),
            defaults={
                "split_field": "expected_revenue",
                "totals_100_percent": True,
                "is_active": False,
            },
        )

        OpportunitySplitType.objects.get_or_create(
            company=self.company,
            split_label=_("Overlay"),
            defaults={
                "split_field": "amount",
                "totals_100_percent": False,
            },
        )
        OpportunitySplitType.objects.get_or_create(
            company=self.company,
            split_label=_("Revenue"),
            defaults={
                "split_field": "amount",
                "totals_100_percent": True,
            },
        )


class OpportunitySplitType(HorillaCoreModel):
    """
    Defines split types (Revenue, Overlay, etc.) .
    Each split type can be configured to total 100% or allow overlays.
    """

    split_label = models.CharField(
        max_length=255,
        verbose_name=_("Split Label"),
        help_text=_("Name of the split type (e.g., Revenue, Overlay)"),
    )

    split_field = models.CharField(
        max_length=100,
        default="amount",
        verbose_name=_("Split Field"),
        help_text=_("Field to split: amount, expected_revenue, etc."),
        choices=[
            ("amount", _("Opportunity - Amount")),
            ("expected_revenue", _("Opportunity - Expected Revenue")),
        ],
    )

    totals_100_percent = models.BooleanField(
        default=True,
        verbose_name=_("Totals 100%"),
        help_text=_("Require splits of this type to total exactly 100%"),
    )

    class Meta:
        """Meta options for OpportunitySplitType."""

        verbose_name = _("Opportunity Split Type")
        verbose_name_plural = _("Opportunity Split Types")
        unique_together = ("company", "split_field", "totals_100_percent")

    def __str__(self):
        return str(self.split_label)

    def is_active_col(self):
        """Return HTML for active status column."""
        html = render_template(
            path="components/toggle_active_col.html",
            context={
                "instance": self,
                "toggle_url": reverse_lazy(
                    "opportunities:opportunity_split_toggle_active",
                    kwargs={"pk": self.pk},
                ),
            },
        )

        return html

    @property
    def is_overlay(self):
        """Overlay splits don't require 100% total."""
        return not self.totals_100_percent


class OpportunitySplit(HorillaCoreModel):
    """
    Represents credit splits for each Opportunity.
    Each record indicates how much credit (percentage or amount)
    a user receives for an opportunity under a given split type.
    """

    opportunity = models.ForeignKey(
        "opportunities.Opportunity",
        on_delete=models.CASCADE,
        related_name="splits",
        verbose_name=_("Opportunity"),
    )

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="opportunity_splits",
        verbose_name=_("Team Member"),
        help_text=_("User receiving credit for this split."),
    )

    split_type = models.ForeignKey(
        "opportunities.OpportunitySplitType",
        on_delete=models.CASCADE,
        related_name="splits",
        verbose_name=_("Split Type"),
        help_text=_("Type of split, such as Revenue or Overlay."),
    )

    split_percentage = models.DecimalField(
        max_digits=6,
        decimal_places=2,
        null=True,
        blank=True,
        verbose_name=_("Split Percentage"),
        help_text=_("Percentage of total credit (e.g., 25.00 for 25%)."),
    )

    split_amount = models.DecimalField(
        max_digits=15,
        decimal_places=2,
        null=True,
        blank=True,
        verbose_name=_("Split Amount"),
        help_text=_(
            "Calculated split amount based on percentage and opportunity amount."
        ),
    )

    OWNER_FIELDS = ["user"]

    class Meta:
        """Meta options for OpportunitySplit."""

        verbose_name = _("Opportunity Split")
        verbose_name_plural = _("Opportunity Splits")

    def actions(self):
        """
        This method for get custom column for action.
        """
        disabled = False
        if self.user == self.opportunity.owner and self.split_type.totals_100_percent:
            disabled = True

        return render_template(
            path="opportunity_split/actions.html",
            context={
                "instance": self,
                "disabled": disabled,
            },
        )
