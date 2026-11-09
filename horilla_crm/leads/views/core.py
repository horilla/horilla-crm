"""Views for Lead model."""

# Standard library imports
from urllib.parse import urlencode

# First party imports (Horilla)
from horilla.auth.mixins import LoginRequiredMixin
from horilla.contrib.core.utils import field_readonly_hidden_if, get_allowed_user_ids
from horilla.contrib.generics.mixins import RecentlyViewedMixin
from horilla.contrib.generics.views import (
    HorillaCardView,
    HorillaChartView,
    HorillaDetailView,
    HorillaGroupByView,
    HorillaKanbanView,
    HorillaListView,
    HorillaNavView,
    HorillaSplitView,
    HorillaView,
)
from horilla.contrib.generics.views.timeline import HorillaTimelineView
from horilla.contrib.utils.middlewares import get_current_request
from horilla.db.models import Avg, Count, Max, Min, Sum
from horilla.urls import reverse_lazy
from horilla.utils.decorators import (
    htmx_required,
    method_decorator,
    permission_required,
    permission_required_or_denied,
)
from horilla.utils.functional import cached_property
from horilla.utils.translation import gettext_lazy as _
from horilla.web import RedirectResponse

# Local imports
from horilla_crm.leads.assignment.owner_lock import owner_locked
from horilla_crm.leads.filters import LeadFilter
from horilla_crm.leads.models import Lead, LeadStatus

CONVERT_TARGET_ADD_PERMS = (
    (_("Accounts"), "accounts.add_account", "accounts.add_own_account"),
    (_("Contacts"), "contacts.add_contact", "contacts.add_own_contact"),
    (
        _("Opportunities"),
        "opportunities.add_opportunity",
        "opportunities.add_own_opportunity",
    ),
)


def missing_convert_targets(user):
    """
    Labels of the models (Accounts/Contacts/Opportunities) the user can't
    create, i.e. holds neither the add nor the add-own permission for.
    """
    return [
        label
        for label, full, own in CONVERT_TARGET_ADD_PERMS
        if not (user.has_perm(full) or user.has_perm(own))
    ]


def user_can_create_convert_targets(user):
    """True only if the user can add an Account, a Contact and an Opportunity."""
    if not user or not user.is_authenticated:
        return False
    return not missing_convert_targets(user)


def _convert_action_hidden_if(obj):
    """
    Hide the Convert action unless the user may convert this lead
    (convert_lead, or convert_own_lead on a lead they own). Missing
    Account/Contact/Opportunity add permissions are explained inside the
    convert modal instead of hiding the button.
    """
    request = get_current_request()
    if not request or not request.user.is_authenticated:
        return True
    user = request.user
    can_convert = user.has_perm("leads.convert_lead") or (
        getattr(obj, "lead_owner_id", None) is not None
        and obj.lead_owner_id in get_allowed_user_ids(user)
        and user.has_perm("leads.convert_own_lead")
    )
    return not can_convert


_owner_field_readonly_hidden_if = field_readonly_hidden_if(Lead, "lead_owner")


def _change_owner_hidden_if(obj):
    """
    Hide Change Owner when the owner field is read-only for the user, or when
    the lead's assignment rule does not let this user change its owner.
    """
    if _owner_field_readonly_hidden_if(obj):
        return True
    request = get_current_request()
    user = getattr(request, "user", None)
    return owner_locked(obj, user)


LINK_RECORDS_ACTION = {
    "permission": "leads.convert_lead",
    "own_permission": "leads.convert_own_lead",
    "owner_field": "lead_owner",
    "action": _("Link Records"),
    "src": "assets/icons/link-record.svg",
    "img_class": "w-4 h-4",
    "attrs": """
                hx-get="{get_link_records_url}"
                hx-target="#modalBox"
                hx-swap="innerHTML"
                onclick="openModal()"
                """,
}


class LeadView(LoginRequiredMixin, HorillaView):
    """
    Render the lead page.
    """

    nav_url = reverse_lazy("leads:leads_nav")
    list_url = reverse_lazy("leads:leads_list")
    kanban_url = reverse_lazy("leads:leads_kanban")
    group_by_url = reverse_lazy("leads:leads_group_by")
    card_url = reverse_lazy("leads:leads_card")
    split_view_url = reverse_lazy("leads:leads_split_view")
    chart_url = reverse_lazy("leads:leads_chart")
    timeline_url = reverse_lazy("leads:leads_timeline")

    def dispatch(self, request, *args, **kwargs):
        view_type = request.GET.get("view_type")
        if view_type == "converted_lead" and request.GET.get("layout") in (
            "kanban",
            "group_by",
            "card",
            "split_view",
            "chart",
        ):
            get_params = request.GET.copy()
            get_params.pop("layout", None)
            query_string = get_params.urlencode()
            redirect_url = request.path
            if query_string:
                redirect_url += f"?{query_string}"

            return RedirectResponse(request=request, redirect_to=redirect_url)

        return super().dispatch(request, *args, **kwargs)


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required(["leads.view_lead", "leads.view_own_lead"]), name="dispatch"
)
class LeadNavbar(LoginRequiredMixin, HorillaNavView):
    """Lead Navbar"""

    search_url = reverse_lazy("leads:leads_list")
    main_url = reverse_lazy("leads:leads_view")
    filterset_class = LeadFilter
    kanban_url = reverse_lazy("leads:leads_kanban")
    group_by_url = reverse_lazy("leads:leads_group_by")
    card_url = reverse_lazy("leads:leads_card")
    split_view_url = reverse_lazy("leads:leads_split_view")
    chart_url = reverse_lazy("leads:leads_chart")
    timeline_url = reverse_lazy("leads:leads_timeline")
    model_name = "Lead"
    model_app_label = "leads"
    exclude_kanban_fields = "lead_owner"
    enable_actions = True
    enable_quick_filters = True
    column_selector_exclude_fields = [
        "message_id",
        "is_convert",
        "converted_contact",
        "converted_opportunity",
        "converted_at",
    ]

    @cached_property
    def custom_view_type(self):
        """Custom view type for lead"""
        custom_view_type = {
            "converted_lead": {"name": _("Converted Lead"), "show_list_only": True},
        }
        return custom_view_type

    @cached_property
    def new_button(self):
        """New button for lead"""
        if self.request.user.has_perm("leads.add_lead") or self.request.user.has_perm(
            "leads.add_own_lead"
        ):
            return {
                "url": f"""{reverse_lazy("leads:leads_create_single")}?new=true""",
                "attrs": {"id": "lead-create"},
            }
        return None


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied(["leads.view_lead", "leads.view_own_lead"]),
    name="dispatch",
)
class LeadListView(LoginRequiredMixin, HorillaListView):
    """
    Lead List view
    """

    model = Lead
    view_id = "leads-list"
    filterset_class = LeadFilter
    export_exclude = [
        "additional_info",
        "is_convert",
        "message_id",
        "converted_contact",
        "converted_opportunity",
        "converted_at",
    ]
    search_url = reverse_lazy("leads:leads_list")
    main_url = reverse_lazy("leads:leads_view")
    max_visible_actions = 5
    enable_quick_filters = True
    columns = [
        "title",
        "first_name",
        "last_name",
        "email",
        "lead_status",
        "lead_source",
        "industry",
        "annual_revenue",
    ]
    bulk_update_fields = [
        "annual_revenue",
        "no_of_employees",
        "lead_source",
        "lead_owner",
        "industry",
        "lead_status",
    ]

    @cached_property
    def col_attrs(self):
        """Column attributes for lead"""
        query_params = {}
        if "section" in self.request.GET:
            query_params["section"] = self.request.GET.get("section")
        query_string = urlencode(query_params)
        return [
            {
                "title": {
                    "hx-get": f"{{get_detail_url}}?{query_string}",
                    "hx-target": "#mainContent",
                    "hx-swap": "outerHTML",
                    "hx-push-url": "true",
                    "hx-select": "#mainContent",
                    "permission": "leads.view_lead",
                    "own_permission": "leads.view_own_lead",
                    "owner_field": "lead_owner",
                }
            }
        ]

    def no_record_add_button(self):
        """No record add button for lead"""
        if self.request.user.has_perm("leads.add_lead") or self.request.user.has_perm(
            "leads.add_own_lead"
        ):
            return {
                "url": f"""{reverse_lazy("leads:leads_create_single")}?new=true""",
                "attrs": 'id="lead-create"',
            }
        return None

    lead_permission = {
        "permission": "leads.change_lead",
        "own_permission": "leads.change_own_lead",
        "owner_field": "lead_owner",
    }
    actions = [
        {
            **lead_permission,
            "action": "Edit",
            "src": "assets/icons/edit.svg",
            "img_class": "w-4 h-4",
            "attrs": """
                        hx-get="{get_edit_url}?new=true"
                        hx-target="#modalBox"
                        hx-swap="innerHTML"
                        onclick="openModal()"
                        """,
        },
        {
            **lead_permission,
            "action": "Change Owner",
            "src": "assets/icons/a2.svg",
            "img_class": "w-4 h-4",
            "hidden_if": _change_owner_hidden_if,
            "attrs": """
                        hx-get="{get_change_owner_url}"
                        hx-target="#modalBox"
                        hx-swap="innerHTML"
                        onclick="openModal()"
                        """,
        },
        {
            "action": "Convert",
            "src": "assets/icons/a3.svg",
            "img_class": "w-4 h-4",
            "hidden_if": _convert_action_hidden_if,
            "attrs": """
                        hx-get="{get_lead_convert_url}"
                        hx-target="#contentModalBox"
                        hx-swap="innerHTML"
                        onclick="openContentModal()"
                        """,
        },
        {
            "action": _("Duplicate"),
            "src": "assets/icons/duplicate.svg",
            "img_class": "w-4 h-4",
            "permission": "leads.add_lead",
            "owner_field": "lead_owner",
            "own_permission": "leads.add_own_lead",
            "attrs": """
                            hx-get="{get_duplicate_url}?duplicate=true"
                            hx-target="#modalBox"
                            hx-swap="innerHTML"
                            onclick="openModal()"
                            """,
        },
        {
            "action": "Delete",
            "src": "assets/icons/a4.svg",
            "img_class": "w-4 h-4",
            "permission": "leads.delete_lead",
            "owner_field": "lead_owner",
            "own_permission": "leads.delete_own_lead",
            "attrs": """
                    hx-post="{get_delete_url}"
                    hx-target="#deleteModeBox"
                    hx-swap="innerHTML"
                    hx-trigger="click"
                    hx-vals='{{"check_dependencies": "true"}}'
                    onclick="openDeleteModeModal()"
                """,
        },
    ]

    def get_queryset(self):
        queryset = super().get_queryset()
        view_type = self.request.GET.get("view_type") or self.get_default_view_type()
        if view_type == "converted_lead":
            queryset = queryset.filter(is_convert=True)
            self.actions = None
            self.no_record_add_button = False
            self.no_record_msg = _("Not found coverted leads")
            self.bulk_update_option = False
        else:
            queryset = queryset.filter(is_convert=False)
        return queryset


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied(["leads.view_lead", "leads.view_own_lead"]),
    name="dispatch",
)
class LeadCardView(LoginRequiredMixin, HorillaCardView):
    """Lead Card (tile) view - same data as list in card layout."""

    model = Lead
    view_id = "leads-card"
    filterset_class = LeadFilter
    search_url = reverse_lazy("leads:leads_list")
    main_url = reverse_lazy("leads:leads_view")
    max_visible_actions = 5
    enable_quick_filters = True
    columns = [
        "title",
        "first_name",
        "email",
        "lead_status",
        "lead_source",
    ]
    actions = LeadListView.actions

    @cached_property
    def col_attrs(self):
        """Column attributes for lead"""
        query_params = {}
        if "section" in self.request.GET:
            query_params["section"] = self.request.GET.get("section")
        query_string = urlencode(query_params)
        return [
            {
                "title": {
                    "hx-get": f"{{get_detail_url}}?{query_string}",
                    "hx-target": "#mainContent",
                    "hx-swap": "outerHTML",
                    "hx-push-url": "true",
                    "hx-select": "#mainContent",
                    "permission": "leads.view_lead",
                    "own_permission": "leads.view_own_lead",
                    "owner_field": "lead_owner",
                }
            }
        ]

    def no_record_add_button(self):
        """No record add button for lead"""
        if self.request.user.has_perm("leads.add_lead") or self.request.user.has_perm(
            "leads.add_own_lead"
        ):
            return {
                "url": f"""{reverse_lazy("leads:leads_create_single")}?new=true""",
                "attrs": 'id="lead-create"',
            }
        return None

    def get_queryset(self):
        queryset = super().get_queryset()
        view_type = self.request.GET.get("view_type") or self.get_default_view_type()
        if view_type == "converted_lead":
            queryset = queryset.filter(is_convert=True)
            self.actions = None
        else:
            queryset = queryset.filter(is_convert=False)
        return queryset


@method_decorator(
    permission_required_or_denied(["leads.view_lead", "leads.view_own_lead"]),
    name="dispatch",
)
class LeadKanbanView(LoginRequiredMixin, HorillaKanbanView):
    """
    Lead Kanban view
    """

    model = Lead
    view_id = "Lead_Kanban"
    filterset_class = LeadFilter
    search_url = reverse_lazy("leads:leads_list")
    main_url = reverse_lazy("leads:leads_view")
    group_by_field = "lead_status"
    exclude_kanban_fields = "lead_owner"
    columns = [
        "title",
        "first_name",
        "email",
        "lead_source",
        "industry",
        "annual_revenue",
    ]

    actions = LeadListView.actions

    @cached_property
    def kanban_attrs(self):
        """Kanban attributes for lead"""
        query_params = self.request.GET.dict()
        query_params = {}
        if "section" in self.request.GET:
            query_params["section"] = self.request.GET.get("section")
        query_string = urlencode(query_params)

        return {
            "hx-get": f"{{get_detail_url}}?{query_string}",
            "hx-target": "#mainContent",
            "hx-swap": "outerHTML",
            "hx-push-url": "true",
            "hx-select": "#mainContent",
            "permission": "leads.view_lead",
            "own_permission": "leads.view_own_lead",
            "owner_field": "lead_owner",
        }

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        group_by = self.get_group_by_field()

        if group_by == "lead_status" and "grouped_items" in context:
            filtered_grouped_items = {}
            num_columns = 0

            for key, group_data in context["grouped_items"].items():
                related = group_data.get("related_obj")
                if related is not None and getattr(related, "is_final", False):
                    continue
                filtered_grouped_items[key] = group_data
                num_columns += 1

            context["grouped_items"] = filtered_grouped_items
            context["num_columns"] = num_columns

        return context

    def get_queryset(self):
        queryset = super().get_queryset()
        view_type = self.request.GET.get("view_type") or self.get_default_view_type()
        if view_type == "converted_lead":
            queryset = queryset.filter(is_convert=True)
            self.actions = None
        else:
            queryset = queryset.filter(is_convert=False)
        return queryset


@method_decorator(
    permission_required_or_denied(["leads.view_lead", "leads.view_own_lead"]),
    name="dispatch",
)
class LeadGroupByView(LoginRequiredMixin, HorillaGroupByView):
    """
    Lead Group By view
    """

    model = Lead
    view_id = "leads-group-by"
    filterset_class = LeadFilter
    search_url = reverse_lazy("leads:leads_list")
    enable_quick_filters = True
    main_url = reverse_lazy("leads:leads_view")
    group_by_field = "lead_status"
    exclude_kanban_fields = "lead_owner"
    max_visible_actions = 5

    columns = [
        "first_name",
        "last_name",
        "title",
        "email",
        "lead_status",
        "lead_source",
        "industry",
        "annual_revenue",
    ]
    actions = LeadListView.actions
    bulk_update_fields = LeadListView.bulk_update_fields

    @cached_property
    def col_attrs(self):
        """Column attributes for lead"""
        query_params = {}
        if "section" in self.request.GET:
            query_params["section"] = self.request.GET.get("section")
        query_string = urlencode(query_params)
        return [
            {
                "title": {
                    "hx-get": f"{{get_detail_url}}?{query_string}",
                    "hx-target": "#mainContent",
                    "hx-swap": "outerHTML",
                    "hx-push-url": "true",
                    "hx-select": "#mainContent",
                    "permission": "leads.view_lead",
                    "own_permission": "leads.view_own_lead",
                    "owner_field": "lead_owner",
                }
            }
        ]

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        group_by = self.get_group_by_field()

        if group_by == "lead_status" and "grouped_items" in context:
            # One query for all columns instead of LeadStatus.objects.get per key
            status_ids = [k for k in context["grouped_items"] if k is not None]
            final_ids = set(
                LeadStatus.objects.filter(pk__in=status_ids, is_final=True).values_list(
                    "pk", flat=True
                )
            )
            filtered_grouped_items = {
                key: group_data
                for key, group_data in context["grouped_items"].items()
                if key not in final_ids
            }
            context["grouped_items"] = filtered_grouped_items

        return context

    def get_queryset(self):
        queryset = super().get_queryset()
        view_type = self.request.GET.get("view_type") or self.get_default_view_type()
        if view_type == "converted_lead":
            queryset = queryset.filter(is_convert=True)
            self.actions = None
        else:
            queryset = queryset.filter(is_convert=False)
        return queryset


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied(["leads.view_lead", "leads.view_own_lead"]),
    name="dispatch",
)
class LeadChartView(LoginRequiredMixin, HorillaChartView):
    """Lead chart view: counts by group-by field using same filters as list/kanban."""

    model = Lead
    view_id = "leads-chart"
    filterset_class = LeadFilter
    search_url = reverse_lazy("leads:leads_list")
    main_url = reverse_lazy("leads:leads_view")
    group_by_field = "lead_status"
    exclude_chart_fields = "lead_owner"
    chart_numeric_metrics = {
        "no_of_employees": ["avg", "min", "max"],
        "lead_score": ["avg", "min", "max"],
    }

    def get_queryset(self):
        queryset = super().get_queryset()
        view_type = self.request.GET.get("view_type") or self.get_default_view_type()
        if view_type == "converted_lead":
            queryset = queryset.filter(is_convert=True)
        else:
            queryset = queryset.filter(is_convert=False)
        return queryset

    def build_chart_payload(
        self, queryset, group_by, value_field=None, value_metric=None
    ):
        """
        Omit final lead stages from chart (same as LeadGroupByView grouped_items).
        Supports optional numeric Y-axis (sum) while preserving this filtering.
        """
        if group_by != "lead_status":
            return super().build_chart_payload(queryset, group_by, value_field)

        field = self.model._meta.get_field(group_by)

        # Decide aggregation: metric(value_field) or Count("pk")
        agg_field_name = "_value"
        if value_field:
            metric = (value_metric or "sum").lower()
            agg_map = {
                "sum": Sum,
                "avg": Avg,
                "min": Min,
                "max": Max,
            }
            agg_cls = agg_map.get(metric, Sum)
            num_field = self.model._meta.get_field(value_field)
            if not self._field_is_numeric_for_chart(num_field):
                return None, _("Selected Y-axis field must be numeric.")
            rows = list(
                queryset.values(group_by)
                .annotate(**{agg_field_name: agg_cls(value_field)})
                .order_by(f"-{agg_field_name}")
            )
        else:
            agg_field_name = "_count"
            rows = list(
                queryset.values(group_by)
                .annotate(_count=Count("pk"))
                .order_by("-_count")
            )

        labels, data, urls = [], [], []
        list_url = str(self.search_url) if self.search_url else ""

        for row in rows:
            key = row[group_by]
            if key is not None:
                try:
                    if LeadStatus.objects.filter(pk=key, is_final=True).exists():
                        continue
                except Exception:
                    pass
            value = row[agg_field_name] or 0
            label = self._label_for_group_key(field, key)
            labels.append(label)
            data.append(value)
            if list_url and key is not None:
                urls.append(self._list_drill_url(group_by, key))
            else:
                urls.append("#")
        return {"labels": labels, "data": data, "urls": urls}, None

    def build_stacked_payload(
        self, queryset, primary, secondary, value_field=None, value_metric=None
    ):
        """
        Drop final lead stages from stacked segments when lead_status is an axis.
        Supports optional numeric Y-axis (sum) while preserving this filtering.
        """

        if primary != "lead_status" and secondary != "lead_status":
            return super().build_stacked_payload(
                queryset, primary, secondary, value_field, value_metric
            )

        def is_final_pk(pk):
            if pk is None:
                return False
            try:
                return LeadStatus.objects.filter(pk=pk, is_final=True).exists()
            except Exception:
                return False

        # Decide aggregation: metric(value_field) or Count("pk")
        agg_field_name = "_value"
        if value_field:
            metric = (value_metric or "sum").lower()
            agg_map = {
                "sum": Sum,
                "avg": Avg,
                "min": Min,
                "max": Max,
            }
            agg_cls = agg_map.get(metric, Sum)
            num_field = self.model._meta.get_field(value_field)
            if not self._field_is_numeric_for_chart(num_field):
                return None, _("Selected Y-axis field must be numeric.")
            rows = list(
                queryset.values(primary, secondary)
                .annotate(**{agg_field_name: agg_cls(value_field)})
                .order_by()
            )
        else:
            agg_field_name = "_count"
            rows = list(
                queryset.values(primary, secondary)
                .annotate(_count=Count("pk"))
                .order_by()
            )
        filtered = []
        for row in rows:
            pk, sk = row[primary], row[secondary]
            if primary == "lead_status" and is_final_pk(pk):
                continue
            if secondary == "lead_status" and is_final_pk(sk):
                continue
            filtered.append(row)
        if not filtered:
            return None, _("No data after excluding final stages.")

        from collections import defaultdict

        field_p = self.model._meta.get_field(primary)
        field_s = self.model._meta.get_field(secondary)
        pivot = defaultdict(lambda: defaultdict(int))
        primary_keys = []
        secondary_keys_order = []
        seen_p, seen_s = set(), set()
        for row in filtered:
            pk, sk = row[primary], row[secondary]
            pivot[pk][sk] += row[agg_field_name] or 0
            if pk not in seen_p:
                seen_p.add(pk)
                primary_keys.append(pk)
            if sk not in seen_s:
                seen_s.add(sk)
                secondary_keys_order.append(sk)
        categories = [self._label_for_group_key(field_p, k) for k in primary_keys]
        series = []
        list_url = str(self.search_url) if self.search_url else ""
        for sk in secondary_keys_order:
            name = self._label_for_group_key(field_s, sk)
            row_data = []
            for pk in primary_keys:
                v = int(pivot[pk].get(sk, 0))
                if list_url and v > 0:
                    row_data.append(
                        {
                            "value": v,
                            "url": self._list_drill_url_two(primary, pk, secondary, sk),
                        }
                    )
                else:
                    row_data.append(v)
            series.append({"name": name, "data": row_data})
        stacked_data = {"categories": categories, "series": series}
        totals = [sum(pivot[pk].values()) if pivot[pk] else 0 for pk in primary_keys]
        urls = []
        if list_url:
            for pk in primary_keys:
                val = pk if pk is not None else ""
                urls.append(self._list_drill_url(primary, val))
        else:
            urls = ["#"] * len(categories)
        return {
            "stackedData": stacked_data,
            "labels": categories,
            "data": totals,
            "urls": urls,
        }, None

    def no_record_add_button(self):
        """No record add button for lead"""
        if self.request.user.has_perm("leads.add_lead") or self.request.user.has_perm(
            "leads.add_own_lead"
        ):
            return {
                "url": f"""{reverse_lazy("leads:leads_create_single")}?new=true""",
                "attrs": {"id": "lead-create"},
            }
        return None


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied(["leads.view_lead", "leads.view_own_lead"]),
    name="dispatch",
)
class LeadSplitView(LoginRequiredMixin, HorillaSplitView):
    """
    Lead Split view: left = tile list, right = simple details on click.
    """

    model = Lead
    view_id = "leads-split"
    filterset_class = LeadFilter
    search_url = reverse_lazy("leads:leads_list")
    main_url = reverse_lazy("leads:leads_view")
    enable_quick_filters = True
    list_column_visibility = False
    split_view_permission = "leads.view_lead"
    split_view_own_permission = "leads.view_own_lead"
    split_view_owner_field = "lead_owner"

    columns = [
        "title",
        "lead_status",
    ]

    no_record_add_button = LeadListView.no_record_add_button
    actions = LeadListView.actions

    def get_queryset(self):
        queryset = super().get_queryset()
        view_type = self.request.GET.get("view_type") or self.get_default_view_type()
        if view_type == "converted_lead":
            queryset = queryset.filter(is_convert=True)
            self.actions = None
            self.no_record_add_button = False
            self.no_record_msg = _("Not found coverted leads")
            self.bulk_update_option = False
        else:
            queryset = queryset.filter(is_convert=False)
        return queryset


@method_decorator(
    permission_required_or_denied(["leads.view_lead", "leads.view_own_lead"]),
    name="dispatch",
)
class LeadTimelineView(LoginRequiredMixin, HorillaTimelineView):
    """Timeline from created_at to updated_at; rows by lead_status."""

    model = Lead
    view_id = "leads-timeline"
    filterset_class = LeadFilter
    search_url = reverse_lazy("leads:leads_list")
    main_url = reverse_lazy("leads:leads_view")
    enable_quick_filters = True
    timeline_start_field = "created_at"
    timeline_end_field = "updated_at"
    timeline_group_by_field = "lead_status"
    timeline_title_field = "title"
    columns = ["title", "first_name", "email", "lead_status"]
    actions = LeadListView.actions

    col_attrs = LeadListView.col_attrs

    def get_queryset(self):
        queryset = super().get_queryset()
        view_type = self.request.GET.get("view_type") or self.get_default_view_type()
        if view_type == "converted_lead":
            queryset = queryset.filter(is_convert=True)
            self.actions = None
        else:
            queryset = queryset.filter(is_convert=False)
        return queryset


@method_decorator(
    permission_required_or_denied(["leads.view_lead", "leads.view_own_lead"]),
    name="dispatch",
)
class LeadDetailView(RecentlyViewedMixin, LoginRequiredMixin, HorillaDetailView):
    """Lead Detail View"""

    model = Lead
    body = [
        "title",
        "first_name",
        "last_name",
        "email",
        "lead_source",
        "industry",
        "lead_owner",
    ]
    excluded_fields = [
        "is_convert",
        "message_id",
        "converted_contact",
        "converted_opportunity",
        "converted_at",
    ]
    pipeline_field = "lead_status"
    tab_url = reverse_lazy("leads:lead_detail_view_tabs")

    def get_pipeline_choices(self):
        """Annotate ``is_final`` from LeadStatus.related_obj (CRM-only)."""
        pipeline = super().get_pipeline_choices()
        if not isinstance(pipeline, list):
            return pipeline
        for choice in pipeline:
            related = choice.get("related_obj")
            choice["is_final"] = bool(
                related is not None and getattr(related, "is_final", False)
            )
        return pipeline

    @cached_property
    def final_stage_action(self):
        """
        Final stage ("Convert") action for lead.

        Always returns a truthy dict so the pipeline template never falls
        back to its generic hx-post to `update_pipeline` for this stage â€”
        that endpoint would set lead_status to the final stage directly
        without creating the Account/Contact/Opportunity records. When the
        user lacks permission to convert, the dict carries no hx-get, so
        the pill renders inert instead of opening the conversion modal.
        """
        if _convert_action_hidden_if(self.object):
            return {
                # Mouse events must stay live (no pointer-events:none) so
                # action_tooltip.js can still show the aria-label tooltip on
                # hover. The click itself is blocked via preventDefault, and
                # !important pins the pill's own resting bg-primary-400/
                # text-primary-600 colors against its hover:bg-primary-600/
                # hover:text-white classes so hovering doesn't visibly change it.
                "hx-on:click": "event.preventDefault();",
                "style": (
                    "cursor:not-allowed;"
                    "background-color:#FBE5E1!important;"
                    "color:#E54F38!important;"
                ),
                "aria-label": _("You don't have permission to convert this lead"),
            }
        return {
            "hx-get": reverse_lazy("leads:convert_lead", kwargs={"pk": self.object.pk}),
            "hx-target": "#contentModalBox",
            "hx-swap": "innerHTML",
            "hx-on:click": "openContentModal();",
        }

    actions = LeadListView.actions

    def get_context_data(self, **kwargs):
        obj = self.get_object()
        context = super().get_context_data(**kwargs)
        if obj.is_convert:
            self.pipeline_field = None
            # A converted lead is read-only; the only thing left is to connect it
            # to the records it belongs to.
            self.actions = [LINK_RECORDS_ACTION]
            context["pipeline_field"] = self.pipeline_field
            context["actions"] = self.actions
        return context
