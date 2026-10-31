"""Cadence detail view."""

# Standard library imports
from functools import cached_property
from urllib.parse import urlparse

# Third-party imports (Django)
from django.utils.html import escape

from horilla.auth.mixins import LoginRequiredMixin
from horilla.contrib.activity.models import Activity
from horilla.contrib.generics.views import HorillaNavView
from horilla.contrib.generics.views.details import HorillaDetailView
from horilla.db.models import Count

# First party imports (Horilla)
from horilla.urls import reverse, reverse_lazy
from horilla.utils.decorators import (
    htmx_required,
    method_decorator,
    permission_required_or_denied,
)
from horilla.utils.translation import gettext_lazy as _

# Local imports
from ..models import Cadence


def get_cadence_previous_url(request, cadence):
    """Return the URL the cadence detail page goes back to.

    That is the page the user opened the cadence from, or the cadence list when
    they came from the cadence report (so Back does not bounce between the two).
    """
    referer_session_key = f"detail_referer_{Cadence._meta.model_name}_{cadence.pk}"
    stored_referer = request.session.get(referer_session_key)

    report_path = reverse("cadences:cadence_report_view")
    if stored_referer and urlparse(stored_referer).path == report_path:
        request.session.pop(referer_session_key, None)
        stored_referer = None

    return stored_referer or reverse("cadences:cadence_view")


@method_decorator(
    permission_required_or_denied(["cadences.view_cadence"]),
    name="dispatch",
)
class CadenceDetailView(LoginRequiredMixin, HorillaDetailView):
    """Detail view for cadence (kanban-style conditions in columns)."""

    model = Cadence
    template_name = "cadence_detail.html"
    body = []
    actions = []

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        followups = list(
            self.object.followups.select_related(
                "branch_from",
                "branch_from__branch_from",
                "email_template",
            )
            .annotate(branch_children_count=Count("branch_children"))
            .order_by("followup_number", "order", "id")
        )
        context["conditions"] = followups
        num_columns = self._display_column_count(followups)
        buckets = self._bucket_followups(followups, num_columns)
        cols_data = self._followups_into_columns(followups, num_columns, buckets)
        context["cadence_columns"] = [
            {
                "rows": cols_data[i],
                "col_num": i + 1,
                # F1 has no parent card, so its "add another" sits at the column bottom.
                "show_standalone_add": i == 0 and bool(cols_data[i]),
            }
            for i in range(num_columns)
        ]
        context["followup_column_count"] = num_columns
        return context

    @staticmethod
    def _display_column_count(followups):
        if not followups:
            return 5
        return max(5, max(f.followup_number for f in followups) + 1)

    @staticmethod
    def _bucket_followups(followups, num_columns):
        buckets = {i: [] for i in range(1, num_columns + 1)}
        for followup in followups:
            bucket_no = max(1, min(num_columns, followup.followup_number))
            buckets[bucket_no].append(followup)
        return buckets

    @staticmethod
    def _status_keys_for_previous_type(previous_type):
        if previous_type == "call":
            return {"scheduled", "completed", "overdue", "cancelled"}
        if previous_type == "task":
            return {key for key, _ in Activity.STATUS_CHOICES}
        return {
            "scheduled",
            "completed",
            "overdue",
            "cancelled",
            "in_progress",
            "not_started",
        }

    @classmethod
    def _can_add_next_for_parent(cls, parent_followup, buckets, num_columns):
        next_bucket_no = parent_followup.followup_number + 1
        if next_bucket_no > num_columns:
            return False
        all_status_keys = cls._status_keys_for_previous_type(
            parent_followup.followup_type
        )
        used_statuses = {
            item.previous_status
            for item in buckets[next_bucket_no]
            if item.previous_status and item.branch_from_id == parent_followup.pk
        }
        return bool(all_status_keys - used_statuses)

    @classmethod
    def _can_add_same_stage_for_source(cls, source_followup, target_bucket_no, buckets):
        if not source_followup:
            return False
        all_status_keys = cls._status_keys_for_previous_type(
            source_followup.followup_type
        )
        used_statuses = {
            item.previous_status
            for item in buckets[target_bucket_no]
            if item.previous_status and item.branch_from_id == source_followup.pk
        }
        return bool(all_status_keys - used_statuses)

    @classmethod
    def _has_branch_child_in_next_bucket(cls, followup, buckets, num_columns):
        next_n = followup.followup_number + 1
        if next_n > num_columns:
            return False
        for item in buckets.get(next_n, []):
            if item.branch_from_id == followup.pk:
                return True
        return False

    @classmethod
    def _expand_fu1_column_slots(cls, rows):
        real = [r for r in rows if r.get("condition")]
        if not real:
            return rows
        real.sort(key=lambda r: (r["condition"].order, r["condition"].pk))
        return cls._expand_order_slots_for_branch_group(real)

    @classmethod
    def _rebuild_column_by_parent_slots(
        cls, row_dicts, followup_number, buckets, prev_column_rows=None
    ):
        real = [r for r in row_dicts if r.get("condition")]
        if not real:
            return row_dicts
        prev_fn = followup_number - 1
        parents = buckets.get(prev_fn, [])
        if not parents:
            real.sort(key=lambda r: (r["condition"].order, r["condition"].pk))
            return cls._expand_order_slots_for_branch_group(real)
        if prev_column_rows is not None:
            parents_ordered = []
            seen = set()
            for row in prev_column_rows:
                c = row.get("condition")
                if not c or c.pk in seen:
                    continue
                seen.add(c.pk)
                if c.followup_number == prev_fn:
                    parents_ordered.append(c)
            parent_ids = {p.pk for p in parents_ordered}
        else:
            parents_ordered = sorted(parents, key=lambda p: (p.order, p.pk))
            parent_ids = {p.pk for p in parents_ordered}
        by_parent = {pid: [] for pid in parent_ids}
        orphans = []
        for r in real:
            bf = r["condition"].branch_from_id
            if bf and bf in parent_ids:
                by_parent[bf].append(r)
            else:
                orphans.append(r)
        for pid in by_parent:
            by_parent[pid].sort(key=lambda r: (r["condition"].order, r["condition"].pk))
        out = []
        for p in parents_ordered:
            group = by_parent.get(p.pk, [])
            if group:
                out.extend(cls._expand_order_slots_for_branch_group(group))
            # Parents with no continuation in this stage contribute no row at all;
            # the flow-arrow script matches cards by pk/position rather than row
            # index, so skipping them just makes the column shorter instead of
            # reserving a blank card.
        if orphans:
            orphans.sort(key=lambda r: (r["condition"].order, r["condition"].pk))
            out.extend(cls._expand_order_slots_for_branch_group(orphans))
        return out

    @classmethod
    def _expand_order_slots_for_branch_group(cls, group_rows):
        max_order = max(r["condition"].order for r in group_rows)
        by_order = {}
        for r in group_rows:
            by_order.setdefault(r["condition"].order, []).append(r)
        out = []
        for s in range(0, max_order + 1):
            if s in by_order:
                out.extend(by_order[s])
            else:
                out.append({"empty_slot": True, "slot_order": s})
        return out

    @classmethod
    def _followups_into_columns(cls, followups, num_columns, buckets):
        _CONDITION_CARD_ICONS = (
            "assets/icons/task.svg",
            "assets/icons/call.svg",
            "assets/icons/email_outline.svg",
        )
        _CONDITION_LABELS = (_("Task"), _("Call"), _("Email"))
        _KIND = ("task", "call", "email")
        icon_by_kind = dict(zip(_KIND, _CONDITION_CARD_ICONS))
        label_by_kind = dict(zip(_KIND, _CONDITION_LABELS))
        cols = [[] for _ in range(num_columns)]
        for followup in followups:
            idx = max(1, min(num_columns, followup.followup_number)) - 1
            kind = followup.followup_type
            fu_n = followup.followup_number
            has_next_child = cls._has_branch_child_in_next_bucket(
                followup, buckets, num_columns
            )
            can_add_next_bucket = cls._can_add_next_for_parent(
                followup, buckets, num_columns
            )
            show_card_add_branch = can_add_next_bucket and not has_next_child
            add_branch_followup_number = fu_n + 1 if show_card_add_branch else None
            source_same_stage = (
                followup.branch_from
                if fu_n >= 2
                and followup.branch_from_id
                and followup.branch_from.followup_number == fu_n - 1
                else None
            )
            can_add_sibling = bool(
                source_same_stage
                and cls._can_add_same_stage_for_source(source_same_stage, fu_n, buckets)
            )
            cols[idx].append(
                {
                    "condition": followup,
                    "icon": icon_by_kind.get(kind, _CONDITION_CARD_ICONS[0]),
                    "kind_label": label_by_kind.get(kind, _CONDITION_LABELS[0]),
                    "kind": kind,
                    "show_card_add_branch": show_card_add_branch,
                    "add_branch_followup_number": add_branch_followup_number,
                    "show_card_add_below_next": False,
                    "can_add_sibling": can_add_sibling,
                    "bottom_add_followup_number": fu_n,
                    "bottom_add_branch_from_id": followup.branch_from_id,
                    "show_delete_followup": getattr(
                        followup, "branch_children_count", 0
                    )
                    == 0,
                }
            )
        for i in range(num_columns):
            fn = i + 1
            if fn == 1:
                cols[i] = cls._expand_fu1_column_slots(cols[i])
            else:
                cols[i] = cls._rebuild_column_by_parent_slots(
                    cols[i], fn, buckets, prev_column_rows=cols[i - 1]
                )
        for col in cols[1:]:
            cls._flag_last_sibling_add(col)
        return cols

    @staticmethod
    def _flag_last_sibling_add(col_rows):
        """Show the "add another" button only under the last card of each sibling group
        (same stage and parent), and only while that parent still has unused statuses.
        """
        last_by_parent = {}
        for row in col_rows:
            if row.get("condition"):
                last_by_parent[row["condition"].branch_from_id] = row
        for row in last_by_parent.values():
            row["show_card_add_below_next"] = row["can_add_sibling"]


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied(["cadences.view_cadence"]), name="dispatch"
)
class CadenceDetailNavbar(LoginRequiredMixin, HorillaNavView):
    """Navbar for the cadence detail page: back, name, View Reports and Edit."""

    search_url = reverse_lazy("cadences:cadence_list_view")
    main_url = reverse_lazy("cadences:cadence_view")
    model_name = "Cadence"
    model_app_label = "cadences"
    nav_width = False
    one_view_only = True
    all_view_types = False
    recently_viewed_option = False
    filter_option = False
    reload_option = False
    search_option = False
    border_enabled = False
    navbar_indication = True

    @cached_property
    def cadence(self):
        """The cadence whose detail page this navbar belongs to."""
        try:
            cadence_pk = int(self.request.GET.get("cadence_pk"))
            return Cadence.objects.filter(pk=cadence_pk).first()
        except (TypeError, ValueError):
            return None

    def get_navbar_indication_attrs(self):
        """Back to the page the cadence was opened from."""
        previous_url = (
            get_cadence_previous_url(self.request, self.cadence)
            if self.cadence
            else reverse("cadences:cadence_view")
        )
        return {
            "title": _("Back"),
            "hx-get": escape(previous_url),
            "hx-target": "#mainContent",
            "hx-swap": "outerHTML",
            "hx-push-url": "true",
            "hx-select": "#mainContent",
        }

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        if self.cadence:
            context["nav_title"] = self.cadence.name
            context["nav_description"] = self.cadence.description or _(
                "Automate sequences of follow-ups for your records."
            )
        return context

    @cached_property
    def new_button(self):
        """Edit the cadence, shown if the user can change it."""
        if self.cadence and self.request.user.has_perm("cadences.change_cadence"):
            return {"url": self.cadence.get_edit_url(), "title": _("Edit")}
        return None

    @cached_property
    def second_button(self):
        """Open the cadence report."""
        if not self.cadence:
            return None
        return {
            "url": reverse_lazy("cadences:cadence_report_view"),
            "title": _("View Reports"),
            "target": "#mainContent",
            "swap": "outerHTML",
            "onclick": "void(0)",
            "attrs": {"hx-select": "#mainContent", "hx-push-url": "true"},
        }
