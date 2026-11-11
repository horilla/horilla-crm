"""Models for horilla.contrib.dashboard app."""

# Standard library imports
import json
import logging

# Third-party imports (Django)
from django.conf import settings
from django.core.validators import MinValueValidator

# First party imports (Horilla)
from horilla.apps import apps
from horilla.contrib.core.models import HorillaContentType, HorillaCoreModel
from horilla.contrib.reports.models import Report
from horilla.contrib.utils.methods import render_template
from horilla.db import models, transaction
from horilla.registry.limiters import limit_content_types
from horilla.registry.permission_registry import permission_exempt_model
from horilla.urls import reverse_lazy
from horilla.utils.choices import OPERATOR_CHOICES
from horilla.utils.translation import gettext_lazy as _
from horilla.utils.upload import upload_path

logger = logging.getLogger(__name__)


class DashboardFolder(HorillaCoreModel):
    """Model for organizing dashboard in folders"""

    name = models.CharField(max_length=255, verbose_name=_("Folder Name"))
    description = models.TextField(blank=True, null=True, verbose_name=_("Description"))
    parent_folder = models.ForeignKey(
        "self",
        on_delete=models.CASCADE,
        blank=True,
        null=True,
        related_name="subfolders",
        verbose_name=_("Folder"),
    )
    favourited_by = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        related_name="favourite_folders",
        blank=True,
        verbose_name=_("Favourited By"),
    )
    folder_owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="folders",
        verbose_name=_("Folder Owner"),
    )

    OWNER_FIELDS = ["folder_owner"]

    class Meta:
        """Meta class for DashboardFolder"""

        ordering = ["name"]
        verbose_name = _("Dashboard Folder")
        verbose_name_plural = _("Dashboard Folders")

    def __str__(self):
        return str(self.name)

    def get_item_type(self):
        """Get the type of item for display purposes"""
        return _("Folder")

    def get_detail_view_url(self):
        """URL to view the folder details"""
        return reverse_lazy(
            "dashboard:dashboard_folder_detail_list", kwargs={"pk": self.pk}
        )

    def actions(self):
        """This method for get custom column for action."""
        return render_template(
            path="folder_custom_actions.html",
            context={"instance": self},
        )

    def actions_detail(self):
        """This method for get custom column for action."""
        return render_template(
            path="folder_actions_detail.html",
            context={"instance": self},
        )


class Dashboard(HorillaCoreModel):
    """Main dashboard model"""

    dashboard_owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="dashboard",
        verbose_name=_("Dashboard Owner"),
    )
    name = models.CharField(max_length=255, verbose_name=_("Dashboard Name"))
    description = models.TextField(blank=True, null=True, verbose_name=_("Description"))
    folder = models.ForeignKey(
        DashboardFolder,
        on_delete=models.CASCADE,
        related_name="dashboard",
        blank=True,
        null=True,
        verbose_name=_("Folder"),
    )
    is_default = models.BooleanField(
        default=False, db_index=True, verbose_name=_("Is Default")
    )
    favourited_by = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        related_name="favourite_dashboards",
        blank=True,
        verbose_name=_("Favourited By"),
    )

    OWNER_FIELDS = ["dashboard_owner"]

    class Meta:
        """Meta class for Dashboard"""

        ordering = ["name"]
        verbose_name = _("Dashboard")
        verbose_name_plural = _("Dashboards")

    def __str__(self):
        return str(self.name)

    def get_item_type(self):
        """Get the type of item for display purposes"""
        return _("Dashboard")

    def get_detail_view_url(self):
        """URL to view the dashboard details"""
        return reverse_lazy("dashboard:dashboard_detail_view", kwargs={"pk": self.pk})

    def get_update_url(self):
        """URL to update the dashboard"""
        return reverse_lazy("dashboard:dashboard_update", kwargs={"pk": self.pk})

    def get_delete_url(self):
        """URL to delete the dashboard"""
        return reverse_lazy("dashboard:dashboard_delete", kwargs={"pk": self.pk})

    def get_change_owner_url(self):
        """URL to change owner"""
        return reverse_lazy("dashboard:dashboard_change_owner", kwargs={"pk": self.pk})

    def get_favourite_toggle_url(self):
        """URL to toggle favourite status"""
        return reverse_lazy(
            "dashboard:dashboard_toggle_favourite", kwargs={"pk": self.pk}
        )

    def actions(self):
        """
        This method for get custom column for action.
        """

        return render_template(
            path="dashboard_custom_actions.html",
            context={"instance": self},
        )

    def actions_detail(self):
        """
        This method for get custom column for action.
        """

        return render_template(
            path="dashboard_actions_detail.html",
            context={"instance": self},
        )

    def can_add_component(self, user):
        """Whether `user` may add a component to this dashboard.

        `add_dashboardcomponent` allows any dashboard; `add_own_dashboardcomponent`
        only dashboards the user owns.
        """
        return user.has_perm("dashboard.add_dashboardcomponent") or (
            user.has_perm("dashboard.add_own_dashboardcomponent")
            and self.dashboard_owner == user
        )

    def is_default_col(self):
        """Return rendered HTML indicating whether this dashboard is the default."""

        html = render_template(
            path="is_default_dashboard.html", context={"instance": self}
        )

        return html

    def save(self, *args, **kwargs):
        """Override save to ensure only one default dashboard per user/company"""
        if self.is_default:
            Dashboard.objects.filter(
                dashboard_owner=self.dashboard_owner,
                company=self.company,
                is_default=True,
            ).exclude(pk=self.pk).update(is_default=False)

        super().save(*args, **kwargs)

    @classmethod
    def get_default_dashboard(cls, user):
        """Get the default dashboard for a user"""
        try:
            return cls.objects.filter(
                dashboard_owner=user,
                company=user.company,
                is_default=True,
                is_active=True,
            ).first()
        except Exception as e:
            logger.error(e)
            return None


class DashboardComponent(HorillaCoreModel):
    """Individual components within a dashboard"""

    COMPONENT_TYPES = [
        ("chart", _("Charts")),
        ("table_data", _("Table Data")),
        ("kpi", _("KPI")),
    ]

    CHART_TYPES = [
        ("column", _("Column Chart")),
        ("line", _("Line Chart")),
        ("pie", _("Pie Chart")),
        ("funnel", _("Funnel")),
        ("bar", _("Bar Chart")),
        ("donut", _("Donut")),
        ("stacked_vertical", _("Stacked Vertical Chart")),
        ("stacked_horizontal", _("Stacked Horizontal Chart")),
        ("scatter", _("Scatter")),
        ("heatmap", _("Heat Map")),
        ("treemap", _("Tree Map")),
        ("area", _("Area Chart")),
        ("sankey", _("Sankey Chart")),
        ("radar", _("Radar Chart")),
    ]

    dashboard = models.ForeignKey(
        Dashboard,
        on_delete=models.CASCADE,
        related_name="components",
        verbose_name=_("Dashboard"),
    )
    name = models.CharField(max_length=255, verbose_name=_("Component Name"))
    component_type = models.CharField(
        max_length=50,
        choices=COMPONENT_TYPES,
        db_index=True,
        verbose_name=_("Component Type"),
    )
    chart_type = models.CharField(
        max_length=50,
        choices=CHART_TYPES,
        blank=True,
        null=True,
        default="column",
        verbose_name=_("Chart Type"),
    )

    reports = models.ForeignKey(
        Report,
        on_delete=models.PROTECT,
        related_name="dashboard",
        verbose_name=_("Reports"),
        null=True,
        blank=True,
    )

    module = models.ForeignKey(
        HorillaContentType,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        limit_choices_to=limit_content_types("dashboard_component_models"),
        verbose_name=_("Module"),
    )

    metric_type = models.CharField(
        max_length=100,
        default="count",
        blank=True,
        null=True,
        verbose_name=_("Metric Type"),
    )

    # Grouping configuration
    grouping_field = models.CharField(
        max_length=100, blank=True, null=True, verbose_name=_("Grouping Field")
    )
    secondary_grouping = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        verbose_name=_("Secondary Grouping"),
    )

    # Y-axis metric configuration for chart components
    y_axis_metric_type = models.CharField(
        max_length=100,
        default="count",
        blank=True,
        null=True,
        verbose_name=_("Y-axis Metric Type"),
    )

    columns = models.TextField(blank=True, null=True, verbose_name=_("Table Columns"))

    # Display and positioning
    sequence = models.PositiveIntegerField(
        default=1, validators=[MinValueValidator(1)], verbose_name=_("Sequence")
    )
    icon = models.ImageField(
        upload_to=upload_path,
        null=True,
        blank=True,
        verbose_name=_("KPI Icon"),
    )

    component_owner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="components",
        verbose_name=_("Component Owner"),
    )

    OWNER_FIELDS = ["component_owner"]

    class Meta:
        """Meta class for DashboardComponent"""

        ordering = ["sequence", "created_at"]
        verbose_name = _("Dashboard Component")
        verbose_name_plural = _("Dashboard Components")

    def __str__(self):
        return f"{self.dashboard.name} - {self.name}"

    @property
    def model_class(self):
        """Get the actual model class"""
        if self.content_type:
            return self.content_type.model_class()
        return None

    def save(self, *args, **kwargs):
        """
        Override save to ensure KPI components get lower sequence numbers (appear first)
        """
        if not self.sequence:
            if self.component_type == "kpi":
                max_kpi_sequence = (
                    DashboardComponent.objects.filter(
                        dashboard=self.dashboard, component_type="kpi", is_active=True
                    ).aggregate(models.Max("sequence"))["sequence__max"]
                    or 0
                )
                self.sequence = max_kpi_sequence + 1
            else:
                max_sequence = (
                    DashboardComponent.objects.filter(
                        dashboard=self.dashboard, is_active=True
                    ).aggregate(models.Max("sequence"))["sequence__max"]
                    or 0
                )
                self.sequence = max_sequence + 1

        super().save(*args, **kwargs)

    @classmethod
    def reorder_components(cls, dashboard, component_order):
        """
        Reorder components, but keep KPI components at the top
        This method now only handles non-KPI components
        """

        with transaction.atomic():
            # Get KPI components count to determine starting sequence for others
            kpi_count = cls.objects.filter(
                dashboard=dashboard, component_type="kpi", is_active=True
            ).count()

            # Update sequences for the reordered components
            for index, component_id in enumerate(component_order):
                try:
                    component = cls.objects.get(
                        id=component_id, dashboard=dashboard, is_active=True
                    )
                    # Only reorder non-KPI components
                    if component.component_type != "kpi":
                        # Start after KPI components
                        component.sequence = kpi_count + index + 1
                        component.save(update_fields=["sequence"])
                except cls.DoesNotExist:
                    continue

    def get_columns_list(self):
        """Return columns as a list regardless of storage format"""
        if not self.columns:
            return []

        try:
            if isinstance(self.columns, str):
                if self.columns.startswith("["):
                    return json.loads(self.columns)
                return [col.strip() for col in self.columns.split(",") if col.strip()]
            if isinstance(self.columns, list):
                return self.columns
            return []
        except Exception as e:
            logger.error(e)
            return []

    def get_columns_with_headers(self):
        """Return columns with their display headers"""
        columns_list = self.get_columns_list
        if not columns_list:
            return []

        try:
            model = None
            for app_config in apps.get_app_configs():
                try:
                    model = apps.get_model(
                        app_label=app_config.label, model_name=self.module.lower()
                    )
                    break
                except LookupError:
                    continue

            if not model:
                return []

            columns_with_headers = []
            for column in columns_list:
                try:
                    field = model._meta.get_field(column)
                    verbose_name = (
                        field.verbose_name or column.replace("_", " ").title()
                    )
                    columns_with_headers.append(
                        {
                            "field": column,
                            "header": verbose_name,
                            "is_foreign_key": hasattr(field, "related_model")
                            and field.many_to_one,
                        }
                    )
                except Exception as e:
                    logger.warning(
                        "Could not get field '%s' for model '%s': %s",
                        column,
                        model.__name__,
                        e,
                    )
                    columns_with_headers.append(
                        {
                            "field": column,
                            "header": column.replace("_", " ").title(),
                            "is_foreign_key": False,
                        }
                    )

            return columns_with_headers
        except Exception as e:
            logger.error("Error getting columns with headers: %s", e)
            return []


@permission_exempt_model
class ComponentCriteria(HorillaCoreModel):
    """Additional criteria/filters for components"""

    component = models.ForeignKey(
        DashboardComponent,
        on_delete=models.CASCADE,
        related_name="conditions",
        verbose_name=_("Component"),
    )
    field = models.CharField(max_length=100, verbose_name=_("Field Name"))
    operator = models.CharField(
        max_length=50, choices=OPERATOR_CHOICES, verbose_name=_("Operator")
    )
    value = models.CharField(max_length=255, blank=True, verbose_name=_("Value"))
    sequence = models.PositiveIntegerField(default=1, verbose_name=_("Sequence"))

    class Meta:
        """Meta class for ComponentCriteria"""

        ordering = ["sequence"]
        verbose_name = _("Component Criteria")
        verbose_name_plural = _("Component Criteria")

    def __str__(self):
        return f"{self.component.name} - {self.field} {self.operator} {self.value}"


class DefaultHomeLayoutOrder(models.Model):
    """
    Store layout order per user: for default home (dashboard=null) or for a
    specific dashboard (dashboard set). Same model for both cases.
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="layout_orders",
        verbose_name=_("User"),
    )
    dashboard = models.ForeignKey(
        "Dashboard",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="user_layout_orders",
        verbose_name=_("Dashboard"),
    )
    order = models.JSONField(
        default=dict,
        blank=True,
        help_text=_(
            'For default home: {"kpi": ["default-kpi-0", ...], "chartsAndTables": [...]}. '
            'For dashboard: {"kpi": [id, ...], "components": [id, ...]}.'
        ),
    )

    class Meta:
        """
        Meta class for DefaultHomeLayoutOrder. Enforce uniqueness of user-dashboard combination,
        """

        unique_together = ("user", "dashboard")
        verbose_name = _("Default Home Layout Order")
        verbose_name_plural = _("Default Home Layout Orders")
        constraints = [
            models.UniqueConstraint(
                fields=["user", "dashboard"],
                name="unique_user_dashboard_layout_order",
            ),
            models.UniqueConstraint(
                fields=["user"],
                condition=models.Q(dashboard__isnull=True),
                name="unique_user_default_home_layout_order",
            ),
        ]

    def __str__(self):
        if self.dashboard_id:
            return _("Layout order for %(user)s - %(dashboard)s") % {
                "user": self.user,
                "dashboard": self.dashboard,
            }
        return _("Default home layout order for %(user)s") % {"user": self.user}


class OnboardingState(models.Model):
    """
    Whether the home page "Get started" guide was dismissed, kept separately for
    each company so dismissing it in one company never changes another. It is
    shared by the company's superusers. No row means the guide is shown.
    """

    company = models.OneToOneField(
        "core.Company",
        on_delete=models.CASCADE,
        related_name="onboarding_state",
        verbose_name=_("Company"),
    )
    is_hidden = models.BooleanField(default=False, verbose_name=_("Hidden"))
    updated_at = models.DateTimeField(auto_now=True, verbose_name=_("Updated At"))

    class Meta:
        """Meta class for OnboardingState: one row per company."""

        verbose_name = _("Onboarding State")
        verbose_name_plural = _("Onboarding States")

    def __str__(self):
        return f"{self.company}: {'hidden' if self.is_hidden else 'shown'}"

    @classmethod
    def is_hidden_for(cls, company):
        """Whether the guide was dismissed for ``company``."""
        return cls.objects.filter(company=company, is_hidden=True).exists()

    @classmethod
    def set_hidden(cls, company, hidden):
        """Dismiss (``True``) or show again (``False``) the guide for ``company`` only."""
        cls.objects.update_or_create(company=company, defaults={"is_hidden": hidden})
