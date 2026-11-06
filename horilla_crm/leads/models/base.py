"""
Models for the Leads module.

This file defines the database models related to leads in the CRM application.
These models represent the structure of lead-related data and include any
relationships, constraints, and behaviors.
"""

# Standard library imports
import logging

# Third-party imports (other)
from colorfield.fields import ColorField

# Third-party imports (Django)
from django.conf import settings
from django.core.validators import EmailValidator
from django.dispatch import receiver
from django_countries.fields import CountryField

from horilla.contrib.core.models import Company, HorillaCoreModel
from horilla.contrib.mail.models import HorillaMailConfiguration
from horilla.contrib.utils.methods import render_template

# First party imports (Horilla)
from horilla.core.exceptions import ValidationError
from horilla.db import models, transaction
from horilla.db.models.signals import post_delete
from horilla.urls import reverse_lazy
from horilla.utils import timezone
from horilla.utils.translation import gettext_lazy as _

logger = logging.getLogger(__name__)

DEFAULT_LEAD_INIT_STAGES = (
    {"name": _("New"), "order": 1, "probability": 10, "is_final": False},
    {"name": _("Contacted"), "order": 2, "probability": 30, "is_final": False},
    {"name": _("Qualified"), "order": 3, "probability": 60, "is_final": False},
    {"name": _("Proposal"), "order": 4, "probability": 80, "is_final": False},
    {"name": _("Lost"), "order": 5, "probability": 0, "is_final": False},
    {"name": _("Convert"), "order": 6, "probability": 100, "is_final": True},
)


class LeadStatus(HorillaCoreModel):
    """
    Lead Status model
    """

    name = models.CharField(max_length=100, verbose_name=_("Status Name"))
    order = models.IntegerField(default=0, verbose_name=_("Status Order"))
    color = ColorField(
        default=None,
        null=True,
        blank=True,
        verbose_name=_("Status Color"),
        help_text=_("Leave blank for default (primary theme colour)."),
    )
    is_final = models.BooleanField(
        default=False, db_index=True, verbose_name=_("Is Final Stage")
    )
    probability = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        verbose_name=_("Probability"),
        help_text=_("Default probability percentage for this stage"),
    )

    class Meta:
        """Meta class for LeadStatus model"""

        verbose_name = _("Lead Stage")
        verbose_name_plural = _("Lead Stages")
        ordering = ["order"]

    def __str__(self):
        return str(self.name)

    def is_final_col(self):
        """Returns the HTML for the is_final column in the list view."""
        html = render_template(
            path="lead_status/is_final_col.html",
            context={"instance": self},
        )
        return html

    def clean(self):
        """Ensure lead stage order is a non-negative integer."""
        if self.order is not None and self.order < 0:
            raise ValidationError(_("Order must be a non-negative integer."))

    def save(self, *args, **kwargs):
        with transaction.atomic():
            previous_final = None
            if self.is_final:
                # Identify and unset the current final stage for the company
                previous_final = (
                    LeadStatus.objects.filter(is_final=True, company=self.company)
                    .exclude(pk=self.pk)
                    .first()
                )
                if previous_final:
                    LeadStatus.objects.filter(pk=previous_final.pk).update(
                        is_final=False
                    )

            if self.pk is None:
                # For new stages, use provided order or next available order
                if not self.order:
                    self.order = self.get_next_order_for_company(self.company)
                self._desired_position = self.order if not self.is_final else None
            else:
                original = LeadStatus.objects.get(pk=self.pk)
                is_final_changed = self.is_final != original.is_final

                # Use provided order for updates, unless it's a new final stage
                if is_final_changed or self.order != original.order:
                    self._desired_position = self.order if not self.is_final else None

            super().save(*args, **kwargs)
            self._reorder_all_statuses(previous_final=previous_final)

    def _reorder_all_statuses(self, previous_final=None):
        """
        Reorder all statuses for the company to ensure sequential ordering with final stage last.
        If desired_position is specified (non-final stage), insert at that position and shift others.
        If desired_position is higher than max order or stage is final, place just before final stage.
        Previous final stage is placed just before the new final stage.
        Only affects statuses within the same company.
        """
        company_statuses = list(
            LeadStatus.objects.filter(company=self.company).order_by("order", "pk")
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
                LeadStatus.objects.filter(pk=status.pk).update(is_final=False)

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

        with transaction.atomic():
            for i, status in enumerate(reordered_statuses, 1):
                LeadStatus.objects.filter(pk=status.pk).update(order=i)

        if hasattr(self, "_desired_position"):
            delattr(self, "_desired_position")

    @staticmethod
    @receiver(post_delete, sender="leads.LeadStatus")
    def handle_bulk_delete(sender, instance, **_kwargs):
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
                    LeadStatus.objects.filter(company=company).order_by("order")
                )
                for i, status in enumerate(remaining_statuses, 1):
                    LeadStatus.objects.filter(pk=status.pk).update(order=i)
                if (
                    was_final
                    and remaining_statuses
                    and not any(s.is_final for s in remaining_statuses)
                ):
                    last_stage = remaining_statuses[-1]
                    LeadStatus.objects.filter(pk=last_stage.pk).update(is_final=True)
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
        return reverse_lazy("leads:edit_lead_stage", kwargs={"pk": self.pk})

    def get_delete_url(self):
        """
        This method to get delete url
        """
        return reverse_lazy("leads:delete_lead_stage", kwargs={"pk": self.pk})


class Lead(HorillaCoreModel):
    """
    Lead Model
    """

    LEAD_SOURCES = [
        ("website", _("Website")),
        ("referral", _("Referral")),
        ("event", _("Event")),
        ("campaign", _("Campaign")),
        ("phone", _("Phone")),
        ("email", _("Email")),
        ("social_media", _("Social Media")),
        ("partner", _("Partner")),
        ("other", _("Other")),
    ]

    INDUSTRY_CHOICES = [
        ("finance", _("Finance")),
        ("healthcare", _("Healthcare")),
        ("manufacturing", _("Manufacturing")),
        ("agriculture", _("Agriculture")),
        ("construction", _("Construction")),
        ("banking", _("Banking")),
        ("education", _("Education")),
        ("insurance", _("Insurance")),
        ("other", _("Other")),
    ]

    title = models.CharField(max_length=100, blank=True, verbose_name=_("Title"))
    first_name = models.CharField(max_length=100, verbose_name=_("First Name"))
    last_name = models.CharField(max_length=100, verbose_name=_("Last Name"))
    lead_owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        default="",
        verbose_name=_("Lead Owner"),
        related_name="lead",
    )
    email = models.EmailField(validators=[EmailValidator()], verbose_name=_("Email"))
    contact_number = models.CharField(
        max_length=100, blank=True, verbose_name=_("Contact Number")
    )
    fax = models.CharField(max_length=100, blank=True, verbose_name=_("Fax"))

    lead_source = models.CharField(
        max_length=100, choices=LEAD_SOURCES, verbose_name=_("Lead Source")
    )
    lead_status = models.ForeignKey(
        LeadStatus,
        on_delete=models.PROTECT,
        related_name="lead",
        verbose_name=_("Lead Stage"),
    )
    lead_company = models.CharField(max_length=100, verbose_name=_("Lead Company"))
    no_of_employees = models.IntegerField(
        null=True, blank=True, verbose_name=_("Number of Employees")
    )
    industry = models.CharField(
        max_length=100, choices=INDUSTRY_CHOICES, verbose_name=_("Industry")
    )
    annual_revenue = models.DecimalField(
        max_digits=15,
        decimal_places=2,
        null=True,
        blank=True,
        verbose_name=_("Annual Revenue"),
    )
    country = CountryField(verbose_name=_("Country"))
    state = models.CharField(blank=True, max_length=100, verbose_name=_("State"))
    city = models.CharField(blank=True, max_length=100, verbose_name=_("City"))
    zip_code = models.CharField(max_length=100, blank=True, verbose_name=_("Zip"))
    requirements = models.TextField(
        blank=True, null=True, verbose_name=_("Requirements")
    )
    is_convert = models.BooleanField(
        default=False,
        null=True,
        blank=True,
        editable=False,
        db_index=True,
        verbose_name=_("Is Converted"),
    )
    converted_contact = models.ForeignKey(
        "contacts.Contact",
        null=True,
        blank=True,
        editable=False,
        on_delete=models.SET_NULL,
        related_name="converted_from_leads",
        verbose_name=_("Converted Contact"),
    )
    converted_opportunity = models.ForeignKey(
        "opportunities.Opportunity",
        null=True,
        blank=True,
        editable=False,
        on_delete=models.SET_NULL,
        related_name="converted_from_leads",
        verbose_name=_("Converted Opportunity"),
    )
    converted_at = models.DateTimeField(
        null=True, blank=True, editable=False, verbose_name=_("Converted At")
    )
    lead_score = models.IntegerField(
        default=0, verbose_name=_("Lead Score"), null=True, blank=True
    )
    message_id = models.CharField(
        max_length=255, unique=True, null=True, blank=True, editable=False
    )

    OWNER_FIELDS = ["lead_owner"]
    CURRENCY_FIELDS = ["annual_revenue"]
    automation_writable_fields = ["is_convert"]

    class Meta:
        """Meta class for Lead model"""

        verbose_name = _("Lead")
        verbose_name_plural = _("Leads")
        # Checked by the conversion and link-records views; without these rows
        # only a superuser could convert, whatever a role granted.
        permissions = (
            ("convert_lead", _("Can Convert Lead")),
            ("convert_own_lead", _("Can Convert Own Lead")),
        )

    def __str__(self):
        return f"{str(self.title)}-{self.id}"

    def save(self, *args, **kwargs):
        """
        Override save method to auto-generate title if not provided
        """
        if not self.title:
            owner_name = getattr(self.lead_owner, "username", str(self.lead_owner))
            self.title = f"{self.lead_company}/{self.first_name}/{owner_name}"

        super().save(*args, **kwargs)

    DYNAMIC_METHODS = ["get_edit_url"]
    # Get field details

    @property
    def is_record_locked(self):
        """A converted lead is read-only; permission checks honour this flag."""
        return bool(self.is_convert)

    def get_detail_url(self):
        """
        This method to get delete url
        """
        return reverse_lazy("leads:leads_detail", kwargs={"pk": self.pk})

    def get_delete_url(self):
        """
        This method to get delete url
        """
        return reverse_lazy("leads:leads_delete", kwargs={"pk": self.pk})

    def get_edit_url(self):
        """
        This method to get edit url
        """
        return reverse_lazy("leads:leads_edit_single", kwargs={"pk": self.pk})

    def get_duplicate_url(self):
        """
        This method to get edit url
        """
        return reverse_lazy("leads:leads_edit_single", kwargs={"pk": self.pk})

    def get_change_owner_url(self):
        """
        This method to get change owner url
        """
        return reverse_lazy("leads:lead_change_owner", kwargs={"pk": self.pk})

    def get_link_records_url(self):
        """
        This method to get the url that links a converted lead to its records
        """
        return reverse_lazy("leads:lead_link_records", kwargs={"pk": self.pk})

    def get_lead_convert_url(self):
        """
        This method to get change owner url
        """
        return reverse_lazy("leads:convert_lead", kwargs={"pk": self.pk})


class EmailToLeadConfig(HorillaCoreModel):
    """Configuration for converting emails to leads."""

    CREATE_AS_CHOICES = [
        ("lead", _("Lead")),
        ("contact", _("Contact")),
    ]

    mail = models.ForeignKey(
        HorillaMailConfiguration,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        verbose_name=_("Incoming Mail"),
    )

    create_as = models.CharField(
        max_length=20,
        choices=CREATE_AS_CHOICES,
        default="lead",
        verbose_name=_("Create As"),
        help_text=_(
            "Choose whether incoming emails matching this configuration create a Lead or a Contact."
        ),
    )

    apply_assignment_rule = models.BooleanField(
        default=True,
        verbose_name=_("Apply Assignment Rule"),
        help_text=_(
            "Applies when created as a Lead. If checked, assignment rules decide "
            "the owner and the selected Owner is used when no rule matches. If "
            "unchecked, the selected Owner is always used."
        ),
    )

    accept_emails_from = models.TextField(
        blank=True,
        null=True,
        help_text=_(
            "Comma-separated list of allowed sender email addresses. Leave blank to accept all."
        ),
        verbose_name=_("Accept Emails From"),
    )
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        verbose_name=_("Owner"),
    )

    keywords = models.TextField(
        blank=False,
        null=False,
        help_text=_(
            "Comma-separated keywords to filter emails. Email must contain at least one keyword in subject OR body."
        ),
        verbose_name=_("Keywords"),
    )

    last_fetched = models.DateTimeField(
        null=True, blank=True, verbose_name=_("Last Fetched On")
    )

    class Meta:
        """Meta options for EmailToLeadConfig."""

        verbose_name = _("Email to Record Config")
        verbose_name_plural = _("Email to Record Config")

    def update_last_fetched(self):
        """Update the last fetched timestamp."""
        self.last_fetched = timezone.now()
        self.save(update_fields=["last_fetched"])

    def get_delete_url(self):
        """
        This method to get delete url
        """
        return reverse_lazy("leads:mail_to_lead_delete_view", kwargs={"pk": self.pk})

    def get_edit_url(self):
        """
        This method to get edit url
        """
        return reverse_lazy("leads:mail_to_lead_update_view", kwargs={"pk": self.pk})

    def get_keywords(self):
        """Return a cleaned list of keywords."""
        if not self.keywords:
            return []
        return [k.strip().lower() for k in self.keywords.split(",") if k.strip()]

    def matches_keywords(self, subject, body):
        """
        Check if email matches keyword filter.
        Returns True if email contains at least one keyword in subject OR body.
        """
        keywords_list = self.get_keywords()

        # If no keywords somehow, reject
        if not keywords_list:
            return False

        subject_lower = subject.lower() if subject else ""
        body_lower = body.lower() if body else ""

        # Check if ANY keyword appears in subject OR body
        for keyword in keywords_list:
            if keyword in subject_lower or keyword in body_lower:
                return True

        return False

    def get_accepted_emails(self):
        """Return a cleaned list of allowed emails or an empty list if accepting all."""
        if not self.accept_emails_from:
            return []  # Empty = accept all
        return [
            e.strip().lower() for e in self.accept_emails_from.split(",") if e.strip()
        ]

    def __str__(self):
        return f"{self.mail}"


class LeadCaptureForm(HorillaCoreModel):
    """Model to store lead capture form configurations"""

    LANGUAGE_CHOICES = [
        (code, _(name)) for code, name, _flag in settings.ALLOWED_LANGUAGES
    ]

    form_name = models.CharField(max_length=255, verbose_name=_("Form Name"))
    selected_fields = models.TextField(verbose_name=_("Selected Fields"))
    return_url_enable = models.BooleanField(
        default=False, verbose_name=_("Enable Return URL")
    )
    return_url = models.URLField(blank=True, null=True, verbose_name=_("Return URL"))
    success_message = models.CharField(
        max_length=255, blank=True, null=True, verbose_name=_("Success Message")
    )
    success_description = models.TextField(
        blank=True, null=True, verbose_name=_("Success Description")
    )
    enable_recaptcha = models.BooleanField(
        default=False, verbose_name=_("Enable Recaptcha")
    )
    language = models.CharField(
        max_length=10,
        choices=LANGUAGE_CHOICES,
        default="en",
        verbose_name=_("Language"),
    )
    header_color = models.CharField(max_length=7, verbose_name=_("Header Color"))
    generated_html = models.TextField(
        blank=True, null=True, verbose_name=_("Generated HTML")
    )
    lead_owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        verbose_name=_("Lead Owner"),
        related_name="lead_capture_forms",
    )
    apply_assignment_rule = models.BooleanField(
        default=False,
        verbose_name=_("Apply Assignment Rule"),
        help_text=_(
            "If checked, assignment rules decide the owner and the selected "
            "Lead Owner is used when no rule matches. If unchecked, the "
            "selected Lead Owner is always used."
        ),
    )

    class Meta:
        """Meta options for LeadCaptureForm."""

        verbose_name = _("Lead Capture Form")
        verbose_name_plural = _("Lead Capture Forms")
        ordering = ["-created_at"]

    def __str__(self):
        return str(self.form_name)
