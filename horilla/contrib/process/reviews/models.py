"""Models for configurable Review Processes."""

# Third-party imports (Django)
from django.conf import settings

from horilla.contrib.core.models import HorillaContentType, HorillaCoreModel, Role
from horilla.contrib.utils.methods import render_template
from horilla.core.exceptions import ValidationError

# First party imports (Horilla)
from horilla.db import models
from horilla.registry.limiters import limit_content_types
from horilla.registry.permission_registry import permission_exempt_model
from horilla.urls import reverse_lazy
from horilla.utils.choices import OPERATOR_CHOICES
from horilla.utils.translation import gettext_lazy as _


class ReviewProcess(HorillaCoreModel):
    """
    A rule that matches records of a given model based on conditions and routes them
    through an ordered set of approval steps.
    """

    title = models.CharField(max_length=256, unique=True, verbose_name=_("Title"))
    method_title = models.CharField(
        max_length=100, editable=False, verbose_name=_("Method Title")
    )
    model = models.ForeignKey(
        HorillaContentType,
        on_delete=models.CASCADE,
        limit_choices_to=limit_content_types("reviews_models"),
        verbose_name=_("Module"),
    )

    # Entry criteria is stored in related `ReviewCondition` rows (`conditions`).
    # Rule criteria is stored in related `ReviewRule` -> `ReviewRuleCondition`.
    review_fields = models.JSONField(
        default=list, blank=True, verbose_name=_("Fields to Review")
    )
    trigger_on_create = models.BooleanField(
        default=True,
        verbose_name=_("When Record Is Created"),
        help_text=_("Start a review when a new record is created."),
    )
    trigger_on_edit = models.BooleanField(
        default=False,
        verbose_name=_("When Record Is Edited"),
        help_text=_("Run the review again when one of the fields to review is edited."),
    )
    notify_on_submission = models.BooleanField(
        default=False, verbose_name=_("Notify on Resubmission")
    )
    notify_on_approval = models.BooleanField(
        default=False, verbose_name=_("Notify on Approval")
    )
    notify_on_rejection = models.BooleanField(
        default=False, verbose_name=_("Notify on Rejection")
    )

    class Meta:
        """Meta class for ReviewProcess modal"""

        verbose_name = _("Review Process")
        verbose_name_plural = _("Review Processes")
        constraints = [
            models.UniqueConstraint(
                fields=["model", "company"],
                condition=models.Q(is_active=True),
                name="unique_active_review_process_per_model_company",
            )
        ]

    def clean(self):
        """Validate required fields before saving the review process."""
        super().clean()
        if not self.title or not self.title.strip():
            raise ValidationError({"title": _("Title is required.")})
        if not self.review_fields:
            raise ValidationError(
                {"review_fields": _("Please select at least one field to review.")}
            )
        if not (self.trigger_on_create or self.trigger_on_edit):
            raise ValidationError(
                _(
                    "Enable at least one of 'When Record Is Created' or 'When Record Is Edited'."
                )
            )
        if self.is_active and self.model_id:
            qs = ReviewProcess.objects.filter(
                model_id=self.model_id,
                company=self.company,
                is_active=True,
            )
            if self.pk:
                qs = qs.exclude(pk=self.pk)
            if qs.exists():
                raise ValidationError(
                    _(
                        "An active review process already exists for this model"
                        " and company. Only one active process is allowed per model per company."
                    )
                )

    def save(self, *args, **kwargs):
        # created_by / updated_by are filled in by HorillaCoreModel.save() after
        # this point, so they must not block validation (rows without them, e.g.
        # seeded data, could otherwise never be saved or toggled).
        self.full_clean(exclude=["created_by", "updated_by"])
        if not self.pk:
            self.method_title = self.title.replace(" ", "_").lower()
        return super().save(*args, **kwargs)

    def get_execute_display(self) -> str:
        """Human-readable 'Execute on'."""
        c, e = self.trigger_on_create, self.trigger_on_edit
        if c and e:
            return str(_("Create and Edit"))
        if c:
            return str(_("Create only"))
        if e:
            return str(_("Edit only"))
        return str(_("Not set"))

    def get_edit_url(self):
        """Return the update form url"""
        return reverse_lazy("reviews:reviews_update_view", kwargs={"pk": self.pk})

    def get_delete_url(self):
        """Rturn the review process delete url"""
        return reverse_lazy("reviews:reviews_delete_view", kwargs={"pk": self.pk})

    def get_detail_url(self):
        """
        This method to get detail url
        """
        return reverse_lazy("reviews:reviews_detail_view", kwargs={"pk": self.pk})

    def is_active_col(self):
        """Return HTML toggle for the is_active column in the list view."""
        return render_template(
            path="components/toggle_active_col.html",
            context={
                "instance": self,
                "toggle_url": reverse_lazy(
                    "reviews:reviews_toggle_active", kwargs={"pk": self.pk}
                ),
            },
        )

    def __str__(self) -> str:
        return str(self.title)


@permission_exempt_model
class ReviewCondition(HorillaCoreModel):
    """
    Filtering conditions for a review process.
    """

    reviews = models.ForeignKey(
        ReviewProcess,
        on_delete=models.CASCADE,
        related_name="conditions",
        verbose_name=_("Review Process"),
    )
    field = models.CharField(max_length=100, verbose_name=_("Field Name"))
    operator = models.CharField(
        max_length=50, choices=OPERATOR_CHOICES, verbose_name=_("Operator")
    )
    value = models.CharField(max_length=255, blank=True, verbose_name=_("Value"))
    logical_operator = models.CharField(
        max_length=3,
        choices=[("and", _("AND")), ("or", _("OR"))],
        default="and",
        verbose_name=_("Logical Operator"),
    )
    order = models.PositiveIntegerField(default=0, verbose_name=_("Order"))

    class Meta:
        """Meta class for ReviewCondition modal"""

        verbose_name = _("Review Condition")
        verbose_name_plural = _("Review Conditions")
        ordering = ["order", "created_at"]

    def __str__(self):
        return f"{self.reviews.title} - {self.field} {self.operator} {self.value}"


@permission_exempt_model
class ReviewRule(HorillaCoreModel):
    """Rule criteria container for a review process."""

    reviews = models.ForeignKey(
        ReviewProcess,
        on_delete=models.CASCADE,
        related_name="rules",
        verbose_name=_("Review Process"),
    )
    approver_type = models.CharField(
        max_length=20,
        choices=[("user", _("User")), ("role", _("Role"))],
        default="user",
        verbose_name=_("Approver Type"),
    )
    approver_users = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        blank=True,
        related_name="reviewses_as_user",
        verbose_name=_("Approver Users"),
    )
    approver_roles = models.ManyToManyField(
        Role,
        blank=True,
        related_name="reviewses_as_role",
        verbose_name=_("Approver Roles"),
    )

    class Meta:
        """Meta class for the ReviewRule  model"""

        verbose_name = _("Review Rule")
        verbose_name_plural = _("Review Rules")

    def __str__(self):
        return f"{self.reviews.title} - Rule"


@permission_exempt_model
class ReviewRuleCondition(HorillaCoreModel):
    """Conditions for the detail rule (applied after entry criteria)."""

    review_rule = models.ForeignKey(
        ReviewRule,
        on_delete=models.CASCADE,
        related_name="conditions",
        verbose_name=_("Review Rule"),
    )
    field = models.CharField(max_length=100, verbose_name=_("Field Name"))
    operator = models.CharField(
        max_length=50, choices=OPERATOR_CHOICES, verbose_name=_("Operator")
    )
    value = models.CharField(max_length=255, blank=True, verbose_name=_("Value"))
    logical_operator = models.CharField(
        max_length=3,
        choices=[("and", _("AND")), ("or", _("OR"))],
        default="and",
        verbose_name=_("Logical Operator"),
    )
    order = models.PositiveIntegerField(default=0, verbose_name=_("Order"))

    class Meta:
        """Meta class for ReviewRuleCondition modal"""

        verbose_name = _("Review Rule Condition")
        verbose_name_plural = _("Review Rule Conditions")
        ordering = ["order", "created_at"]

    def __str__(self):
        return f"{self.review_rule.reviews.title} - {self.field} {self.operator} {self.value}"


# @permission_exempt_model
class ReviewJob(HorillaCoreModel):
    """Review task for an approver against a matched record."""

    STATUS_PENDING = "pending"
    STATUS_APPROVED = "approved"
    STATUS_REJECTED = "rejected"
    STATUS_CHOICES = [
        (STATUS_PENDING, _("Pending")),
        (STATUS_APPROVED, _("Approved")),
        (STATUS_REJECTED, _("Rejected")),
    ]

    reviews = models.ForeignKey(
        ReviewProcess,
        on_delete=models.CASCADE,
        related_name="jobs",
        verbose_name=_("Review Process"),
    )
    review_rule = models.ForeignKey(
        ReviewRule,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="jobs",
        verbose_name=_("Review Rule"),
    )
    content_type = models.ForeignKey(
        HorillaContentType,
        on_delete=models.CASCADE,
        verbose_name=_("Content Type"),
    )
    object_id = models.PositiveIntegerField(verbose_name=_("Object ID"))
    content_object = models.GenericForeignKey("content_type", "object_id")
    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="review_jobs",
        verbose_name=_("Assigned To"),
    )
    review_fields_snapshot = models.JSONField(
        default=dict,
        blank=True,
        verbose_name=_("Review Fields Snapshot"),
    )
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default=STATUS_PENDING,
        db_index=True,
        verbose_name=_("Status"),
    )
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="reviewed_jobs",
        verbose_name=_("Reviewed By"),
    )
    reviewed_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name=_("Reviewed At"),
    )
    review_note = models.TextField(blank=True, verbose_name=_("Review Note"))

    class Meta:
        """Meta class for ReviewJob modal"""

        verbose_name = _("Review Job")
        verbose_name_plural = _("Review Jobs")
        ordering = ["status", "-created_at"]
        unique_together = (
            "reviews",
            "review_rule",
            "content_type",
            "object_id",
            "assigned_to",
        )

    def __str__(self):
        return f"{self.reviews} - {self.assigned_to} ({self.get_status_display()})"

    def record(self):
        """Return the related record"""
        return str(self.content_object) if self.content_object else "-"

    def approvers(self):
        """
        Display all approvers for this process+record tuple.

        The review jobs list deduplicates rows across parallel approvers, so showing only
        `assigned_to` can be misleading on that merged row.
        """
        jobs = ReviewJob.all_objects.filter(
            is_active=True,
            status=ReviewJob.STATUS_PENDING,
            reviews_id=self.reviews_id,
            content_type_id=self.content_type_id,
            object_id=self.object_id,
        ).select_related("assigned_to")
        names = sorted(
            {
                str(job.assigned_to)
                for job in jobs
                if getattr(job.assigned_to, "pk", None)
            }
        )
        return ", ".join(names) if names else "-"

    def get_review_url(self):
        """Return review detail url"""
        return reverse_lazy(
            "reviews:review_job_detail_view",
            kwargs={"pk": self.pk},
        )
