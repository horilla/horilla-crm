"""Opportunity detail view and detail tab/activity/notes/history section views."""

# First party imports (Horilla)
from horilla.auth.mixins import LoginRequiredMixin
from horilla.contrib.activity.views import HorillaActivitySectionView
from horilla.contrib.generics.mixins import RecentlyViewedMixin
from horilla.contrib.generics.views import (
    HorillaDetailSectionView,
    HorillaDetailTabView,
    HorillaDetailView,
    HorillaHistorySectionView,
    HorillaNotesAttachementSectionView,
)
from horilla.db.models import ForeignKey
from horilla.urls import reverse_lazy
from horilla.utils.decorators import method_decorator, permission_required_or_denied
from horilla.utils.functional import cached_property  # type: ignore
from horilla.utils.translation import gettext_lazy as _
from horilla.web import Http404

# Local imports
from horilla_crm.opportunities.forms import OpportunitySingleForm
from horilla_crm.opportunities.models import Opportunity

from .base import OpportunityListView


@method_decorator(
    permission_required_or_denied(
        ["opportunities.view_opportunity", "opportunities.view_own_opportunity"]
    ),
    name="dispatch",
)
class OpportunityDetailView(RecentlyViewedMixin, LoginRequiredMixin, HorillaDetailView):
    """Detail view for opportunities."""

    model = Opportunity
    pipeline_field = "stage"
    tab_url = reverse_lazy("opportunities:opportunity_detail_view_tabs")
    actions = OpportunityListView.actions

    body = [
        "name",
        "amount",
        "expected_revenue",
        "quantity",
        "close_date",
        "probability",
        "forecast_category",
    ]

    def get_badges(self):
        """Get badges for opportunity detail view based on stage type."""
        badges = []
        obj = self.get_object()

        if obj.stage and hasattr(obj.stage, "stage_type"):
            stage_type = obj.stage.stage_type
            if stage_type == "won":
                badges.append(
                    {
                        "label": _("Closed Won"),
                        "class": "bg-green-600",
                        "icon": "fa-solid fa-check",
                        "icon_class": "text-green-600",
                        "icon_bg_class": "bg-green-100",
                    }
                )
            elif stage_type == "lost":
                badges.append(
                    {
                        "label": _("Closed Lost"),
                        "class": "bg-red-600",
                        "icon": "fa-solid fa-times",
                        "icon_class": "text-red-600",
                        "icon_bg_class": "bg-red-100",
                    }
                )

        return badges

    def _pipeline_choice(self, *args, is_final=False, **kwargs):
        """CRM helper: attach ``is_final`` (not part of HorillaDetailView)."""
        choice = self._make_pipeline_choice(*args, **kwargs)
        choice["is_final"] = bool(is_final)
        return choice

    def get_pipeline_choices(self):
        """
        Override to group Closed Won and Closed Lost into a single "Closed" option.

        Uses ``related_obj`` on each pill (same pattern as HorillaKanbanView).
        ``is_final`` is set here only — Closed Lost may not have model.is_final=True.
        """
        if not self.pipeline_field:
            return []
        try:
            obj = self.get_object()
        except Http404:
            return []

        field = self.model._meta.get_field(self.pipeline_field)
        current_value = getattr(obj, self.pipeline_field)

        pipeline = []

        if isinstance(field, ForeignKey):
            related_model = field.related_model
            order_field = None
            try:
                order_field = related_model._meta.get_field("order")
            except Exception:
                pass
            queryset = related_model.objects.all()

            if (
                hasattr(related_model, "company")
                and hasattr(obj, "company")
                and obj.company
            ):
                queryset = queryset.filter(company=obj.company)

            if order_field:
                queryset = queryset.order_by("order")

            current_order = (
                getattr(current_value, "order", None) if current_value else None
            )
            current_id = current_value.id if current_value else None
            current_stage_type = (
                getattr(current_value, "stage_type", None) if current_value else None
            )

            closed_won_stage = None
            closed_lost_stage = None
            closed_stage_order = None
            is_current_closed = False
            is_closed_lost = current_stage_type == "lost"

            for related_obj in queryset:
                stage_type = getattr(related_obj, "stage_type", None)

                # Collect closed stages
                if stage_type == "won":
                    closed_won_stage = related_obj
                    if related_obj.id == current_id:
                        is_current_closed = True
                        closed_stage_order = getattr(related_obj, "order", None)
                elif stage_type == "lost":
                    closed_lost_stage = related_obj
                    if related_obj.id == current_id:
                        is_current_closed = True
                        closed_stage_order = getattr(related_obj, "order", None)
                else:
                    # Regular open stages
                    is_completed = False
                    is_current = related_obj.id == current_id

                    # If current stage is "Closed Lost", don't mark other stages as completed
                    # They should appear gray/ash instead of green
                    if not is_closed_lost and current_order is not None:
                        related_order = getattr(related_obj, "order", None)
                        is_completed = (
                            related_order is not None and related_order < current_order
                        )

                    pipeline.append(
                        self._pipeline_choice(
                            str(related_obj),
                            related_obj.id,
                            is_completed,
                            is_current,
                            related_obj=related_obj,
                            is_final=bool(getattr(related_obj, "is_final", False)),
                        )
                    )

            # Add "Closed" as a single option if closed stages exist
            if closed_won_stage or closed_lost_stage:
                # Determine if closed is completed (if current stage is after closed stages)
                is_closed_completed = False
                if current_order is not None and closed_stage_order is not None:
                    is_closed_completed = closed_stage_order < current_order
                elif (
                    current_stage_type not in ["won", "lost"]
                    and current_order is not None
                ):
                    # If we have a closed stage order, check if current is after it
                    if closed_won_stage:
                        closed_order = getattr(closed_won_stage, "order", None)
                        if closed_order and current_order > closed_order:
                            is_closed_completed = True
                    elif closed_lost_stage:
                        closed_order = getattr(closed_lost_stage, "order", None)
                        if closed_order and current_order > closed_order:
                            is_closed_completed = True

                # If current stage is closed, show the actual stage name
                if is_current_closed and current_value:
                    # Check if it's closed (won or lost) - both need custom styling
                    is_closed = current_stage_type in ["won", "lost"]
                    pipeline.append(
                        self._pipeline_choice(
                            str(current_value),
                            current_value.id,
                            is_closed_completed,
                            True,
                            related_obj=current_value,
                            use_custom_colors=is_closed,
                            is_final=True,
                        )
                    )
                else:
                    # Show "Closed" option that opens the selection modal
                    pipeline.append(
                        self._pipeline_choice(
                            _("Closed"),
                            "closed",
                            is_closed_completed,
                            False,
                            related_obj=closed_won_stage or closed_lost_stage,
                            use_custom_colors=False,
                            is_final=True,
                        )
                    )
        else:
            return []

        return pipeline

    @cached_property
    def final_stage_action(self):
        """Final stage action for opportunity - opens closed stage selection modal."""
        return {
            "hx-get": reverse_lazy(
                "opportunities:select_closed_stage", kwargs={"pk": self.object.pk}
            ),
            "hx-target": "#modalBox",
            "hx-swap": "innerHTML",
            "onclick": "openModal()",
        }

    def get_pipeline_custom_colors(self):
        """
        Get custom colors for pipeline stages.
        Returns a dict with bg_color, text_color, and hover_color (optional).
        If None, default colors will be used.
        """
        obj = self.get_object()
        if obj.stage and hasattr(obj.stage, "stage_type"):
            stage_type = obj.stage.stage_type
            if stage_type == "won":
                return {
                    "bg_color": "bg-green-600",
                    "text_color": "text-white",
                    "hover_color": None,  # No hover for closed won
                }
            if stage_type == "lost":
                return {
                    "bg_color": "bg-red-600",
                    "text_color": "text-white",
                    "hover_color": None,  # No hover for closed lost
                }
        return None


@method_decorator(
    permission_required_or_denied(
        ["opportunities.view_opportunity", "opportunities.view_own_opportunity"]
    ),
    name="dispatch",
)
class OpportunityDetailViewTabView(LoginRequiredMixin, HorillaDetailTabView):
    """Detail view tab view for opportunities."""

    def _prepare_detail_tabs(self):
        self.object_id = self.request.GET.get("object_id")
        self.model = Opportunity
        super()._prepare_detail_tabs()

    urls = {
        "details": "opportunities:opportunity_details_tab",
        "activity": "opportunities:opportunity_activity_detail_view",
        "related_lists": "opportunities:opportunity_related_lists",
        "notes_attachments": "opportunities:opportunity_notes_attachments",
        "history": "opportunities:opportunity_history_tab_view",
    }


@method_decorator(
    permission_required_or_denied(
        ["opportunities.view_opportunity", "opportunities.view_own_opportunity"]
    ),
    name="dispatch",
)
class OpportunityDetailTab(LoginRequiredMixin, HorillaDetailSectionView):
    """Detail tab view for opportunities."""

    model = Opportunity
    form_class = OpportunitySingleForm
    non_editable_fields = ["expected_revenue", "forecast_category", "probability"]


@method_decorator(
    permission_required_or_denied(
        ["opportunities.view_opportunity", "opportunities.view_own_opportunity"]
    ),
    name="dispatch",
)
class OpportunityActivityTabView(LoginRequiredMixin, HorillaActivitySectionView):
    """
    Activity Tab View
    """

    model = Opportunity


@method_decorator(
    permission_required_or_denied(
        ["opportunities.view_opportunity", "opportunities.view_own_opportunity"]
    ),
    name="dispatch",
)
class OpportunitiesNotesAndAttachments(
    LoginRequiredMixin, HorillaNotesAttachementSectionView
):
    """Notes and attachments section view for opportunities."""

    model = Opportunity


@method_decorator(
    permission_required_or_denied(
        ["opportunities.view_opportunity", "opportunities.view_own_opportunity"]
    ),
    name="dispatch",
)
class OpportunityHistoryTabView(LoginRequiredMixin, HorillaHistorySectionView):
    """
    History Tab View
    """

    model = Opportunity
