"""Views for managing opportunity splits on individual opportunities."""

# Standard library imports
from decimal import Decimal

# Third-party imports (Django)
from django.contrib import messages

# First party imports (Horilla)
from horilla.auth.mixins import LoginRequiredMixin
from horilla.auth.models import User
from horilla.contrib.generics.views import HorillaTabView
from horilla.contrib.generics.views.details import check_record_change_access
from horilla.contrib.utils.middlewares import get_active_company
from horilla.shortcuts import get_object_or_404, render
from horilla.urls import reverse_lazy
from horilla.utils.decorators import htmx_required, method_decorator
from horilla.utils.translation import gettext_lazy as _
from horilla.views.generic import TemplateView, View
from horilla.web import HttpResponse, HxTriggerResponse, ScriptResponse

# Local imports
from horilla_crm.opportunities.models import (
    Opportunity,
    OpportunitySettings,
    OpportunitySplit,
    OpportunitySplitType,
    OpportunityTeamMember,
)
from horilla_crm.opportunities.views.opportunity_split.settings import (
    SplitEnabledRequiredMixin,
)


def can_manage_splits(user, opportunity):
    """
    Same rule as the other related tabs: superuser, the global
    add_opportunitysplit permission, or change access on the opportunity
    (change_opportunity, or change_own_opportunity on a record the user owns).
    """
    if getattr(user, "is_superuser", False) or user.has_perm(
        "opportunities.add_opportunitysplit"
    ):
        return True
    return opportunity is not None and check_record_change_access(user, opportunity)


class OpportunityChangeAccessMixin:
    """Deny split views unless the user can manage splits on the opportunity."""

    def _get_target_opportunity(self):
        """Resolve the opportunity from the URL, split id, or ?id= query param."""
        opportunity_id = self.kwargs.get("opportunity_id")
        if opportunity_id is None and self.kwargs.get("split_id") is not None:
            split = OpportunitySplit.objects.filter(id=self.kwargs["split_id"]).first()
            return split.opportunity if split else None
        if opportunity_id is None:
            opportunity_id = self.request.GET.get("id") or self.request.POST.get("id")
        if not str(opportunity_id or "").isdigit():
            return None
        return Opportunity.objects.filter(id=opportunity_id).first()

    def dispatch(self, request, *args, **kwargs):
        """Return 403 unless the user may manage splits on the opportunity."""
        if not can_manage_splits(request.user, self._get_target_opportunity()):
            return render(
                request,
                "403.html",
                {"message": _("You don't have permission to manage splits.")},
                status=403,
            )
        return super().dispatch(request, *args, **kwargs)


@method_decorator(htmx_required, name="dispatch")
class ManageOpportunitySplit(
    LoginRequiredMixin,
    SplitEnabledRequiredMixin,
    OpportunityChangeAccessMixin,
    TemplateView,
):
    """
    Content view for each split type tab
    """

    template_name = "opportunity_split/manage_opportunity_spilt.html"


@method_decorator(htmx_required, name="dispatch")
class OpportunitySplitTabView(
    LoginRequiredMixin,
    SplitEnabledRequiredMixin,
    OpportunityChangeAccessMixin,
    HorillaTabView,
):
    """
    Tab view for opportunity splits - displays Revenue and Overlay tabs
    """

    view_id = "opportunity-splits-tab-view"
    background_class = "bg-primary-100 rounded-md"

    def setup(self, request, *args, **kwargs):
        """Initialize split tabs before rendering the tab container."""
        super().setup(request, *args, **kwargs)
        self.tabs = self.get_split_tabs()

    def get_split_tabs(self):
        """Get split type tabs dynamically"""
        tabs = []
        company = None
        opportunity_id = None

        if self.request and self.request.user.is_authenticated:
            company = get_active_company(self.request)
            # Get opportunity_id from query parameter
            opportunity_id = self.request.GET.get("id")

        if not company or not opportunity_id:
            return tabs

        split_types = OpportunitySplitType.objects.filter(
            company=company, is_active=True
        ).order_by("created_at")

        query_params = self.request.GET.copy()

        for split_type in split_types:
            url = reverse_lazy(
                "opportunities:opportunity_split_tab_content",
                kwargs={
                    "opportunity_id": opportunity_id,
                    "split_type_id": split_type.id,
                },
            )
            if query_params:
                url = f"{url}?{query_params.urlencode()}"

            tab = {
                "title": str(split_type.split_label),
                "url": url,
                "target": f"split-type-{split_type.id}-content",
                "id": f"split-type-{split_type.id}-view",
            }
            tabs.append(tab)

        return tabs


@method_decorator(htmx_required, name="dispatch")
class OpportunitySplitTabContentView(
    LoginRequiredMixin,
    SplitEnabledRequiredMixin,
    OpportunityChangeAccessMixin,
    TemplateView,
):
    """
    Content view for each split type tab
    """

    template_name = "opportunity_split/split_tab_content.html"

    def get_context_data(self, **kwargs):
        """Build context for one split-type tab with users, totals, and rows."""
        context = super().get_context_data(**kwargs)
        opportunity_id = self.kwargs.get("opportunity_id")
        split_type_id = self.kwargs.get("split_type_id")

        opportunity = get_object_or_404(Opportunity, id=opportunity_id)
        split_type = get_object_or_404(OpportunitySplitType, id=split_type_id)

        # Get existing splits
        existing_splits = OpportunitySplit.objects.filter(
            opportunity=opportunity, split_type=split_type
        ).select_related("user")

        # Calculate totals
        total_percentage = sum(s.split_percentage for s in existing_splits) or Decimal(
            "0"
        )
        total_amount = sum(s.split_amount for s in existing_splits) or Decimal("0")

        # Get available users based on settings
        users = self._get_available_users(opportunity)

        # Check settings
        team_selling_enabled = OpportunitySettings.is_team_selling_enabled(
            get_active_company(self.request)
        )
        allow_all_users = OpportunitySettings.allow_all_users_in_splits_enabled(
            get_active_company(self.request)
        )
        if existing_splits.exists():
            last_row = existing_splits.count()
        else:
            last_row = 0

        row_index = last_row + 1

        context.update(
            {
                "row_index": row_index,
                "opportunity": opportunity,
                "split_type": split_type,
                "existing_splits": existing_splits,
                "total_percentage": total_percentage,
                "total_amount": total_amount,
                "users": users,
                "next_row_index": existing_splits.count() + 1,
                "team_selling_enabled": team_selling_enabled,
                "allow_all_users": allow_all_users,
                "currency": get_active_company(self.request).currency
                or self.request.user.currency,
            }
        )

        return context

    def _get_available_users(self, opportunity):
        """
        Get users available for split assignment based on settings.

        Returns:
            QuerySet of User objects
        """

        team_selling_enabled = OpportunitySettings.is_team_selling_enabled(
            get_active_company(self.request)
        )
        allow_all_users = OpportunitySettings.allow_all_users_in_splits_enabled(
            get_active_company(self.request)
        )

        # If allow_all_users is True OR team selling is disabled, show all users
        if allow_all_users or not team_selling_enabled:
            users = User.objects.filter(
                is_active=True, company=get_active_company(self.request)
            ).order_by("first_name", "last_name", "username")

            # Mark which users are team members for display purposes
            if team_selling_enabled:
                team_member_ids = set(
                    opportunity.opportunity_team_members.values_list(
                        "user_id", flat=True
                    )
                )
                for user in users:
                    user.is_team_member = user.id in team_member_ids

            return users

        # Otherwise, show only team members
        team_member_user_ids = opportunity.opportunity_team_members.values_list(
            "user_id", flat=True
        )

        if team_member_user_ids:
            users = User.objects.filter(
                id__in=team_member_user_ids, is_active=True
            ).order_by("first_name", "last_name", "username")

            # Mark all as team members
            for user in users:
                user.is_team_member = True

            return users

        # Fallback to all active users if no team members exist
        return User.objects.filter(
            is_active=True, company=get_active_company(self.request)
        ).order_by("first_name", "last_name", "username")


@method_decorator(htmx_required, name="dispatch")
class SaveOpportunitySplitsView(
    LoginRequiredMixin,
    SplitEnabledRequiredMixin,
    OpportunityChangeAccessMixin,
    View,
):
    """
    Save all splits for a specific split type
    """

    def post(self, request, opportunity_id, split_type_id):
        """Handle POST request to save opportunity splits."""
        opportunity = get_object_or_404(Opportunity, id=opportunity_id)
        split_type = get_object_or_404(OpportunitySplitType, id=split_type_id)
        company = get_active_company(request)

        if not OpportunitySettings.is_split_enabled(company):
            messages.error(request, _("Opportunity splits are not enabled."))
            return ScriptResponse(reload=True, extra="closeContentModal();")

        splits_data = self._parse_splits_data(request.POST)

        validation_result = self._validate_splits(splits_data, split_type, opportunity)
        if not validation_result["valid"]:
            splits_with_amounts = []
            for split_data in splits_data:
                try:
                    user_id = int(split_data["user_id"])
                    percentage = Decimal(split_data["percentage"])
                except Exception:
                    continue

                amount = self._calculate_split_amount(
                    opportunity, split_type, percentage
                )

                splits_with_amounts.append(
                    {
                        "user": User.objects.filter(id=user_id).first(),
                        "user_id": user_id,
                        "split_percentage": percentage,
                        "split_amount": amount,
                        "id": None,
                    }
                )

            total_percentage = sum(
                s["split_percentage"] for s in splits_with_amounts
            ) or Decimal("0")
            total_amount = sum(
                s["split_amount"] for s in splits_with_amounts
            ) or Decimal("0")

            context = {
                "opportunity": opportunity,
                "split_type": split_type,
                "existing_splits": splits_with_amounts,
                "users": User.objects.filter(company=company, is_active=True),
                "error": validation_result["error"],
                "total_percentage": total_percentage,
                "total_amount": total_amount,
                "currency": get_active_company(self.request).currency
                or self.request.user.currency,
            }
            return render(request, "opportunity_split/split_tab_content.html", context)

        # Check if team selling is enabled and if we should auto-add members
        team_selling_enabled = OpportunitySettings.is_team_selling_enabled(company)
        allow_all_users = OpportunitySettings.allow_all_users_in_splits_enabled(company)

        # Get existing team member user IDs
        existing_team_member_ids = set(
            opportunity.opportunity_team_members.values_list("user_id", flat=True)
        )

        # Collect users who need to be added to the team
        users_to_add = []
        for split_data in splits_data:
            if split_data["user_id"]:
                user_id = int(split_data["user_id"])
                if (
                    team_selling_enabled
                    and allow_all_users
                    and user_id not in existing_team_member_ids
                ):
                    users_to_add.append(user_id)

        if users_to_add:
            self._add_users_to_team(opportunity, users_to_add, company)

        OpportunitySplit.objects.filter(
            opportunity=opportunity, split_type=split_type
        ).delete()

        # Create new splits
        for split_data in splits_data:
            if split_data["user_id"] and split_data["percentage"]:
                split_amount = self._calculate_split_amount(
                    opportunity, split_type, Decimal(split_data["percentage"])
                )

                OpportunitySplit.objects.create(
                    company=company,
                    opportunity=opportunity,
                    user_id=split_data["user_id"],
                    split_type=split_type,
                    split_percentage=Decimal(split_data["percentage"]),
                    split_amount=split_amount,
                )

        messages.success(request, _("Opportunity splits saved successfully"))
        return HxTriggerResponse(
            id="tab-splits-btn",
            extra="closeContentModal();",
        )

    def _add_users_to_team(self, opportunity, user_ids, company):
        """
        Add users to the opportunity team with default settings

        Args:
            opportunity: The Opportunity instance
            user_ids: List of user IDs to add
            company: The company instance
        """

        added_users = []
        for user_id in user_ids:
            # Check if already exists (extra safety check)
            if not OpportunityTeamMember.objects.filter(
                opportunity=opportunity, user_id=user_id
            ).exists():
                try:
                    user = User.objects.get(id=user_id, company=company, is_active=True)

                    # Create team member with default role and access
                    OpportunityTeamMember.objects.create(
                        company=company,
                        opportunity=opportunity,
                        user=user,
                        team_role="other",
                        opportunity_access="read",
                    )
                    added_users.append(user.get_full_name() or user.username)
                except User.DoesNotExist:
                    continue

        if added_users:
            messages.info(
                self.request,
                _("Added to opportunity team: {}").format(", ".join(added_users)),
            )

    def _parse_splits_data(self, post_data):
        """Parse split data from POST request"""
        splits = []
        i = 1

        while f"user_id_{i}" in post_data:
            user_id = post_data.get(f"user_id_{i}")
            percentage = post_data.get(f"percentage_{i}", "0")

            if user_id and percentage:
                splits.append(
                    {
                        "user_id": user_id,
                        "percentage": percentage.replace("%", "").strip(),
                    }
                )
            i += 1

        return splits

    def _validate_splits(self, splits_data, split_type, opportunity):
        """Validate split data"""
        if not splits_data:
            return {"valid": False, "error": _("At least one split must be added.")}

        try:
            total_percentage = sum(
                Decimal(split["percentage"]) for split in splits_data
            )
        except Exception:
            return {"valid": False, "error": _("Invalid percentage value.")}

        if split_type.totals_100_percent:
            if total_percentage != Decimal("100.00"):
                return {
                    "valid": False,
                    "error": _(
                        f"Total percentage must equal 100%. Current total: {total_percentage}%"
                    ),
                }

        for split in splits_data:
            percentage = Decimal(split["percentage"])
            if percentage < 0 or percentage > 100:
                return {
                    "valid": False,
                    "error": _("Percentage must be between 0 and 100."),
                }

        user_ids = [split["user_id"] for split in splits_data]
        if len(user_ids) != len(set(user_ids)):
            return {
                "valid": False,
                "error": _(
                    "Cannot assign multiple splits to the same user for one split type."
                ),
            }

        return {"valid": True}

    def _calculate_split_amount(self, opportunity, split_type, percentage):
        """Calculate split amount based on percentage and opportunity field"""
        if split_type.split_field == "amount":
            base_amount = opportunity.amount or Decimal("0")
        elif split_type.split_field == "expected_revenue":
            base_amount = opportunity.expected_revenue or Decimal("0")
        else:
            base_amount = Decimal("0")

        return (base_amount * percentage) / Decimal("100")


@method_decorator(htmx_required, name="dispatch")
class AddSplitRowView(
    LoginRequiredMixin,
    SplitEnabledRequiredMixin,
    OpportunityChangeAccessMixin,
    View,
):
    """Add a new empty split row (HTMX)"""

    template_name = "opportunity_split/split_row.html"

    def get(self, request, opportunity_id, split_type_id):
        """Return a new empty split row"""
        opportunity = get_object_or_404(Opportunity, id=opportunity_id)
        split_type = get_object_or_404(OpportunitySplitType, id=split_type_id)

        max_index = 0
        for key in request.GET.keys():
            if key.startswith("percentage_") or key.startswith("user_id_"):
                try:
                    index = int(key.split("_")[-1])
                    max_index = max(max_index, index)
                except (ValueError, IndexError):
                    pass

        # If no existing rows found, check existing splits in database
        if max_index == 0:
            existing_count = OpportunitySplit.objects.filter(
                opportunity=opportunity, split_type=split_type
            ).count()
            max_index = existing_count

        row_index = max_index + 1

        context = {
            "row_index": row_index,
            "opportunity": opportunity,
            "split_type": split_type,
            "users": self._get_available_users(request, opportunity),
            "team_selling_enabled": OpportunitySettings.is_team_selling_enabled(
                get_active_company(request)
            ),
            "allow_all_users": OpportunitySettings.allow_all_users_in_splits_enabled(
                get_active_company(request)
            ),
            "currency": get_active_company(self.request).currency
            or self.request.user.currency,
        }

        return render(request, self.template_name, context)

    def _get_available_users(self, request, opportunity):
        """
        Get users available for split assignment based on settings.

        Returns:
            QuerySet of User objects
        """
        team_selling_enabled = OpportunitySettings.is_team_selling_enabled(
            get_active_company(request)
        )
        allow_all_users = OpportunitySettings.allow_all_users_in_splits_enabled(
            get_active_company(request)
        )

        # If allow_all_users is True OR team selling is disabled, show all users
        if allow_all_users or not team_selling_enabled:
            users = User.objects.filter(
                is_active=True, company=get_active_company(request)
            ).order_by("first_name", "last_name", "username")

            # Mark which users are team members for display purposes
            if team_selling_enabled:
                team_member_ids = set(
                    opportunity.opportunity_team_members.values_list(
                        "user_id", flat=True
                    )
                )
                for user in users:
                    user.is_team_member = user.id in team_member_ids

            return users

        # Otherwise, show only team members
        team_member_user_ids = opportunity.opportunity_team_members.values_list(
            "user_id", flat=True
        )

        if team_member_user_ids:
            users = User.objects.filter(
                id__in=team_member_user_ids, is_active=True
            ).order_by("first_name", "last_name", "username")

            # Mark all as team members
            for user in users:
                user.is_team_member = True

            return users

        # Fallback to all active users if no team members exist
        return User.objects.filter(
            is_active=True, company=get_active_company(request)
        ).order_by("first_name", "last_name", "username")


@method_decorator(htmx_required, name="dispatch")
class DeleteSplitRowView(
    LoginRequiredMixin,
    SplitEnabledRequiredMixin,
    OpportunityChangeAccessMixin,
    View,
):
    """Delete a split row and redistribute percentage to owner if totals must be 100%"""

    template_name = "opportunity_split/split_tab_content.html"

    def delete(self, request, split_id):
        """Delete the split and return updated form"""
        split = get_object_or_404(OpportunitySplit, id=split_id)

        if split.company != get_active_company(request):
            messages.error(
                request, _("You don't have permission to delete this split.")
            )
            return HttpResponse(status=403)

        opportunity = split.opportunity
        split_type = split.split_type
        deleted_percentage = split.split_percentage

        if split_type.totals_100_percent and split.user == opportunity.owner:
            messages.error(
                request,
                "You cannot delete the owner's split because totals must always equal 100%.",
            )
            if request.GET.get("delete") == "true":
                return HxTriggerResponse(id="tab-splits-btn")

            existing_splits = OpportunitySplit.objects.filter(
                opportunity=opportunity, split_type=split_type
            ).select_related("user")

            context = self._build_context(
                request, opportunity, split_type, existing_splits
            )
            return render(request, self.template_name, context)

        try:
            split.delete()
            messages.success(
                request, f"Split for {split.user.get_full_name()} deleted successfully."
            )
        except Exception as e:
            messages.error(request, f"Failed to delete split: {str(e)}")
            existing_splits = OpportunitySplit.objects.filter(
                opportunity=opportunity, split_type=split_type
            ).select_related("user")
            context = self._build_context(
                request, opportunity, split_type, existing_splits
            )
            return render(request, self.template_name, context)

        if split_type.totals_100_percent and deleted_percentage > 0:
            owner_split, _created = OpportunitySplit.objects.get_or_create(
                opportunity=opportunity,
                split_type=split_type,
                user=opportunity.owner,
                defaults={
                    "company": get_active_company(request),
                    "split_percentage": Decimal("0"),
                    "split_amount": Decimal("0"),
                },
            )

            owner_split.split_percentage += deleted_percentage
            base_amount = (
                opportunity.amount
                if split_type.split_field == "amount"
                else opportunity.expected_revenue
            ) or Decimal("0")
            owner_split.split_amount = (
                base_amount * owner_split.split_percentage
            ) / Decimal("100")
            owner_split.save()

        if request.GET.get("delete") == "true":
            return HxTriggerResponse(id="tab-splits-btn")

        existing_splits = OpportunitySplit.objects.filter(
            opportunity=opportunity, split_type=split_type
        ).select_related("user")

        context = self._build_context(request, opportunity, split_type, existing_splits)
        return render(request, self.template_name, context)

    def _build_context(self, request, opportunity, split_type, existing_splits):
        total_percentage = sum(s.split_percentage for s in existing_splits) or Decimal(
            "0"
        )
        total_amount = sum(s.split_amount for s in existing_splits) or Decimal("0")

        users = self._get_available_users(request, opportunity)
        team_selling_enabled = OpportunitySettings.is_team_selling_enabled(
            get_active_company(request)
        )
        allow_all_users = OpportunitySettings.allow_all_users_in_splits_enabled(
            get_active_company(request)
        )

        row_index = existing_splits.count() + 1

        return {
            "row_index": row_index,
            "opportunity": opportunity,
            "split_type": split_type,
            "existing_splits": existing_splits,
            "total_percentage": total_percentage,
            "total_amount": total_amount,
            "users": users,
            "next_row_index": row_index,
            "team_selling_enabled": team_selling_enabled,
            "allow_all_users": allow_all_users,
            "currency": get_active_company(self.request).currency
            or self.request.user.currency,
        }

    def _get_available_users(self, request, opportunity):
        """Get users available for split assignment based on settings."""
        team_selling_enabled = OpportunitySettings.is_team_selling_enabled(
            get_active_company(request)
        )
        allow_all_users = OpportunitySettings.allow_all_users_in_splits_enabled(
            get_active_company(request)
        )

        if allow_all_users or not team_selling_enabled:
            users = User.objects.filter(
                is_active=True, company=get_active_company(request)
            ).order_by("first_name", "last_name", "username")

            if team_selling_enabled:
                team_member_ids = set(
                    opportunity.opportunity_team_members.values_list(
                        "user_id", flat=True
                    )
                )
                for user in users:
                    user.is_team_member = user.id in team_member_ids

            return users

        team_member_user_ids = opportunity.opportunity_team_members.values_list(
            "user_id", flat=True
        )

        if team_member_user_ids:
            users = User.objects.filter(
                id__in=team_member_user_ids, is_active=True
            ).order_by("first_name", "last_name", "username")

            for user in users:
                user.is_team_member = True

            return users

        return User.objects.filter(
            is_active=True, company=get_active_company(request)
        ).order_by("first_name", "last_name", "username")


@method_decorator(htmx_required, name="dispatch")
class RecalculateTotalsView(
    LoginRequiredMixin,
    SplitEnabledRequiredMixin,
    OpportunityChangeAccessMixin,
    View,
):
    """Recalculate and return updated totals"""

    template_name = "opportunity_split/totals_row.html"

    def get(self, request, opportunity_id, split_type_id):
        """Calculate totals from current form data"""
        opportunity = get_object_or_404(Opportunity, id=opportunity_id)
        split_type = get_object_or_404(OpportunitySplitType, id=split_type_id)

        total_percentage = Decimal("0")
        total_amount = Decimal("0")

        # Get base amount for calculations
        if split_type.split_field == "amount":
            base_amount = opportunity.amount or Decimal("0")
        else:
            base_amount = opportunity.expected_revenue or Decimal("0")

        # Collect all percentage values from GET params
        for key in request.GET.keys():
            if key.startswith("percentage_"):
                percentage_str = request.GET.get(key, "").replace("%", "").strip()
                if percentage_str:
                    try:
                        percentage = Decimal(percentage_str)
                        total_percentage += percentage
                        amount = (base_amount * percentage) / Decimal("100")
                        total_amount += amount
                    except Exception:
                        pass

        context = {
            "opportunity": opportunity,
            "split_type": split_type,
            "total_percentage": total_percentage,
            "total_amount": total_amount,
            "currency": get_active_company(self.request).currency
            or self.request.user.currency,
        }

        return render(request, self.template_name, context)


@method_decorator(htmx_required, name="dispatch")
class RecalculateSplitRowView(
    LoginRequiredMixin,
    SplitEnabledRequiredMixin,
    OpportunityChangeAccessMixin,
    View,
):
    """Recalculate a single split row AND totals"""

    def get(self, request, opportunity_id, split_type_id):
        """Handle GET request to recalculate a single split row and totals."""
        opportunity = get_object_or_404(Opportunity, id=opportunity_id)
        split_type = get_object_or_404(OpportunitySplitType, id=split_type_id)

        # Get the row_index from the request - this is the ACTUAL row being edited
        row_index = request.GET.get("row_index")
        changed_field = request.GET.get("changed_field", "percentage")

        # Validate row_index exists
        if not row_index:
            return HttpResponse("Missing row_index", status=400)

        # Get base amount
        if split_type.split_field == "amount":
            base_amount = opportunity.amount or Decimal("0")
        else:
            base_amount = opportunity.expected_revenue or Decimal("0")

        if changed_field == "percentage":
            # Calculate amount from percentage
            percentage_str = (
                request.GET.get(f"percentage_{row_index}", "0").replace("%", "").strip()
            )
            try:
                percentage = Decimal(percentage_str)
                amount = (base_amount * percentage) / Decimal("100")
            except Exception:
                percentage = Decimal("0")
                amount = Decimal("0")

            # Calculate totals from ALL percentages in the form
            total_percentage = Decimal("0")
            total_amount = Decimal("0")

            for key in request.GET.keys():
                if key.startswith("percentage_"):
                    pct_str = request.GET.get(key, "").replace("%", "").strip()
                    if pct_str:
                        try:
                            pct = Decimal(pct_str)
                            total_percentage += pct
                            total_amount += (base_amount * pct) / Decimal("100")
                        except Exception:
                            pass

            context = {
                "amount": amount,
                "percentage": percentage,
                "row_index": row_index,
                "opportunity": opportunity,
                "split_type": split_type,
                "total_percentage": total_percentage,
                "total_amount": total_amount,
                "currency": get_active_company(self.request).currency
                or self.request.user.currency,
            }
            return render(
                request, "opportunity_split/split_row_amount_with_totals.html", context
            )
        amount_str = request.GET.get(f"amount_{row_index}", "0").strip()
        try:
            amount = Decimal(amount_str)
            if base_amount > 0:
                percentage = (amount * Decimal("100")) / base_amount
            else:
                percentage = Decimal("0")
        except Exception:
            amount = Decimal("0")
            percentage = Decimal("0")

        # Calculate totals - we need to use the NEW percentage for this row
        total_percentage = Decimal("0")
        total_amount = Decimal("0")

        for key in request.GET.keys():
            if key.startswith("percentage_"):
                # Extract the index from the key
                try:
                    key_index = key.split("_")[1]
                except Exception:
                    continue

                if key_index == row_index:
                    # Use the newly calculated percentage for this row
                    total_percentage += percentage
                    total_amount += amount
                else:
                    # Use existing percentage for other rows
                    pct_str = request.GET.get(key, "").replace("%", "").strip()
                    if pct_str:
                        try:
                            pct = Decimal(pct_str)
                            total_percentage += pct
                            total_amount += (base_amount * pct) / Decimal("100")
                        except Exception:
                            pass

        context = {
            "amount": amount,
            "percentage": percentage,
            "row_index": row_index,
            "opportunity": opportunity,
            "split_type": split_type,
            "total_percentage": total_percentage,
            "total_amount": total_amount,
            "currency": get_active_company(self.request).currency
            or self.request.user.currency,
        }
        return render(
            request,
            "opportunity_split/split_row_percentage_with_totals.html",
            context,
        )
