"""
This module defines models for storing user preferences related to Kanban grouping,
saved filters, pinned views, and quick filters in the Horilla platform.
"""

# Django imports
# Standard library imports
import logging

# Third-party imports (Django)
from django.conf import settings

from horilla.apps import apps
from horilla.contrib.utils.middlewares import _thread_local
from horilla.core.exceptions import ValidationError
from horilla.db import models
from horilla.registry.permission_registry import permission_exempt_model

# First party imports (Horilla)
from horilla.utils import timezone
from horilla.utils.translation import gettext_lazy as _

logger = logging.getLogger(__name__)


@permission_exempt_model
class KanbanGroupBy(models.Model):
    """
    Model to store user preferences for grouping in Kanban and Group By views.
    view_type separates settings: 'kanban' for kanban board, 'group_by' for group-by list.
    """

    VIEW_TYPE_CHOICES = [
        ("kanban", _("Kanban")),
        ("group_by", _("Group By")),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        verbose_name=_("Column User"),
        related_name="kanban_column",
    )
    model_name = models.CharField(
        max_length=100,
        help_text=_("Name of the model (e.g., 'User') to group by."),
    )
    app_label = models.CharField(max_length=100)
    view_type = models.CharField(
        max_length=20,
        choices=VIEW_TYPE_CHOICES,
        default="kanban",
        help_text=_("Whether this setting is for Kanban view or Group By view."),
    )
    field_name = models.CharField(
        max_length=100,
        help_text=_(
            "Name of the field that can be used for grouping (ChoiceField or ForeignKey)."
        ),
    )
    all_objects = models.Manager()

    def get_model_groupby_fields(
        self, exclude_fields=None, include_fields=None, user=None
    ):
        """
        Retrieve valid fields for grouping in the selected model.
        When user is provided, excludes fields with 'hidden' (don't show) permission.
        """
        if exclude_fields is None:
            exclude_fields = []
        # Always exclude country from kanban/group_by choices across all models
        exclude_fields = list(exclude_fields) + ["country"]
        # The company field is only offered when "all companies" is enabled.
        request = getattr(_thread_local, "request", None)
        session = getattr(request, "session", None)
        if session is not None and not session.get("show_all_companies", False):
            exclude_fields.append("company")

        try:
            model = apps.get_model(app_label=self.app_label, model_name=self.model_name)
            choices = []

            for field in model._meta.get_fields():
                if field.name in exclude_fields:
                    continue

                if include_fields is not None and field.name not in include_fields:
                    continue

                if isinstance(field, models.CharField) and field.choices:
                    choices.append((field.name, field.verbose_name or field.name))
                elif isinstance(field, models.ForeignKey):
                    choices.append((field.name, field.verbose_name or field.name))

            if user and choices:
                # Local imports
                from ..utils import filter_hidden_fields

                field_names = [c[0] for c in choices]
                allowed = filter_hidden_fields(user, model, field_names)
                choices = [c for c in choices if c[0] in allowed]

            return choices
        except (LookupError, ValueError) as e:
            logger.error(
                "Error retrieving model groupby fields for %s.%s: %s",
                self.app_label,
                self.model_name,
                e,
            )
            return []

    def clean(self):
        """
        Validate that the field_name is a valid ChoiceField or ForeignKey in the selected model.
        Respects field-level permissions when user is available from request.
        """
        request = getattr(_thread_local, "request", None)
        user = getattr(request, "user", None) if request else None
        choices = self.get_model_groupby_fields(user=user)
        if not self.field_name:
            return

        if not any(self.field_name == choice[0] for choice in choices):
            raise ValidationError(
                f"'{self.field_name}' is not a valid ChoiceField or ForeignKey in model '{self.model_name}'."
            )

    def save(self, *args, **kwargs):
        """
        Run validation before saving.
        Override the unique constraint by deleting existing entries.
        """
        self.clean()
        request = getattr(_thread_local, "request")
        existing = KanbanGroupBy.all_objects.filter(
            model_name=self.model_name,
            app_label=self.app_label,
            user=request.user,
            view_type=self.view_type,
        )

        # Delete them before saving this one
        if existing.exists():
            existing.delete()

        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.model_name} by {self.field_name}"

    class Meta:
        """
        Meta options for the KanbanGroupBy model.
        """

        unique_together = ("model_name", "app_label", "user", "view_type")


@permission_exempt_model
class TimelineSpanBy(models.Model):
    """
    Per-user persisted timeline bar start/end date fields (like KanbanGroupBy for grouping).
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        verbose_name=_("User"),
        related_name="timeline_span_settings",
    )
    model_name = models.CharField(
        max_length=100,
        help_text=_("Model name for which timeline span fields apply."),
    )
    app_label = models.CharField(max_length=100)
    start_field = models.CharField(
        max_length=100,
        help_text=_("Field used as bar start date."),
    )
    end_field = models.CharField(
        max_length=100,
        help_text=_(
            "Field used as bar end date (may equal start for single-day bars)."
        ),
    )
    all_objects = models.Manager()

    def get_model_date_fields(self, user=None):
        """Return (field_name, verbose_name) for DateField/DateTimeField on the model."""
        from django.db import models as django_models

        choices = []
        try:
            model = apps.get_model(app_label=self.app_label, model_name=self.model_name)
        except (LookupError, ValueError):
            return choices
        for field in model._meta.get_fields():
            if not getattr(field, "concrete", True):
                continue
            if isinstance(
                field, (django_models.DateField, django_models.DateTimeField)
            ):
                choices.append(
                    (
                        field.name,
                        str(getattr(field, "verbose_name", None) or field.name),
                    )
                )
        if user and choices:
            from ..utils import filter_hidden_fields

            allowed = filter_hidden_fields(user, model, [c[0] for c in choices])
            choices = [c for c in choices if c[0] in allowed]
        return choices

    def clean(self):
        """Validate start_field and end_field are allowed date fields."""
        request = getattr(_thread_local, "request", None)
        user = getattr(request, "user", None) if request else None
        choices = self.get_model_date_fields(user=user)
        choice_names = {c[0] for c in choices}
        if self.start_field and self.start_field not in choice_names:
            raise ValidationError(
                _("'%(field)s' is not a valid date field for this model.")
                % {"field": self.start_field}
            )
        if self.end_field and self.end_field not in choice_names:
            raise ValidationError(
                _("'%(field)s' is not a valid date field for this model.")
                % {"field": self.end_field}
            )

    def save(self, *args, **kwargs):
        """Replace existing row for same user/model/app (single preference row)."""
        self.clean()
        user = self.user
        request = getattr(_thread_local, "request", None)
        if request and getattr(request, "user", None).is_authenticated:
            user = request.user
        if user and user.is_authenticated:
            existing = TimelineSpanBy.all_objects.filter(
                model_name=self.model_name,
                app_label=self.app_label,
                user=user,
            )
            if existing.exists():
                existing.delete()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.model_name} timeline {self.start_field} → {self.end_field}"

    class Meta:
        """Meta for timeline model"""

        unique_together = ("model_name", "app_label", "user")
        verbose_name = _("Timeline Span Settings")
        verbose_name_plural = _("Timeline Span Settings")


@permission_exempt_model
class SavedFilterList(models.Model):
    """
    Model to store saved filter lists for users.
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="saved_filter_lists",
    )
    name = models.CharField(max_length=100)
    model_name = models.CharField(max_length=100)
    filter_params = models.JSONField()
    is_public = models.BooleanField(
        default=False,
        help_text=_(
            "When set, this filter is available to all users in this list/position."
        ),
    )
    created_at = models.DateTimeField(default=timezone.now)
    all_objects = models.Manager()

    class Meta:
        """
        Meta options for the SavedFilterList model.
        """

        unique_together = ["user", "name", "model_name"]
        indexes = [
            models.Index(fields=["user", "model_name"]),
            models.Index(fields=["model_name", "is_public"]),
        ]

    def __str__(self):
        return f"{self.name} ({self.user.username} - {self.model_name})"

    def get_filter_params(self):
        """
        Returns the filter parameters as a dictionary.
        """
        return self.filter_params


@permission_exempt_model
class PinnedView(models.Model):
    """
    Model to store pinned views for users.
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="pinned_views"
    )
    model_name = models.CharField(max_length=100)
    view_type = models.CharField(max_length=100)
    pinned_at = models.DateTimeField(auto_now=True)
    all_objects = models.Manager()

    class Meta:
        """
        Meta options for the PinnedView model.
        """

        unique_together = ["user", "model_name"]
        indexes = [models.Index(fields=["user", "model_name"])]


class QuickFilter(models.Model):
    """Store user's quick filter preferences for list views"""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="quick_filters"
    )
    app_label = models.CharField(max_length=100)
    model_name = models.CharField(max_length=100)
    field_name = models.CharField(max_length=100)
    display_order = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        """
        Meta options for the QuickFilter model.
        """

        unique_together = ("user", "app_label", "model_name", "field_name")
        ordering = ["display_order", "created_at"]

    def __str__(self):
        return f"{self.user.username} - {self.model_name} - {self.field_name}"
