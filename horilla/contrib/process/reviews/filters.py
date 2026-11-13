"""
Filters for the reviews app
"""

# First party imports (Horilla)
from horilla.contrib.core.mixins import OwnerFiltersetMixin
from horilla.contrib.generics.filters import HorillaFilterSet

# First party imports (Horilla)
from horilla.db.models import Exists, OuterRef, Q

# Local imports
from .models import ReviewJob, ReviewProcess


class ReviewProcessFilter(OwnerFiltersetMixin, HorillaFilterSet):
    """
    Review Process class for filtering Process model instances.
    """

    class Meta:
        """
        meta class for Review Process Filter
        """

        model = ReviewProcess
        fields = "__all__"
        exclude = ["additional_info", "id", "review_fields"]
        search_fields = ["title", "method_title", "model__model"]


class ReviewJobFilter(OwnerFiltersetMixin, HorillaFilterSet):
    """
    Review Job class for filtering Process model instances.
    """

    def filter_search(self, queryset, name, value):
        """
        Search review process title and any approver on the same record (parallel jobs).

        The list shows one row per process+record but approvers may be on sibling rows;
        `Exists` matches if any pending job for that tuple has an assignee matching the term.
        """
        search_fields = getattr(self.Meta, "search_fields", [])
        if not value or not search_fields:
            return queryset

        stripped = value.strip()
        if not stripped:
            return queryset

        queries = Q()
        for field in search_fields:
            queries |= Q(**{f"{field}__icontains": stripped})

        user_q = (
            Q(assigned_to__first_name__icontains=stripped)
            | Q(assigned_to__last_name__icontains=stripped)
            | Q(assigned_to__username__icontains=stripped)
            | Q(assigned_to__email__icontains=stripped)
        )
        # Full-name support: "First Last" (and vice versa) should match approvers.
        if " " in stripped:
            first_part, second_part = stripped.split(None, 1)
            user_q |= (
                Q(assigned_to__first_name__icontains=first_part)
                & Q(assigned_to__last_name__icontains=second_part)
            ) | (
                Q(assigned_to__first_name__icontains=second_part)
                & Q(assigned_to__last_name__icontains=first_part)
            )
        sibling_approver = ReviewJob.all_objects.filter(
            reviews_id=OuterRef("reviews_id"),
            content_type_id=OuterRef("content_type_id"),
            object_id=OuterRef("object_id"),
            is_active=True,
            status=ReviewJob.STATUS_PENDING,
        ).filter(user_q)
        queries |= Q(Exists(sibling_approver))

        return queryset.filter(queries)

    class Meta:
        """
        meta class for Review Job Filter
        """

        model = ReviewJob
        fields = "__all__"
        exclude = ["id", "additional_info", "review_fields_snapshot"]
        search_fields = [
            "reviews__title",
            "assigned_to__first_name",
            "assigned_to__last_name",
            "review_note",
        ]
        name_split_fields = ["assigned_to__first_name", "assigned_to__last_name"]
