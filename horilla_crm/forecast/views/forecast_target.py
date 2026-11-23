"""
Views for managing Forecast Targets, including creation, update, deletion,
and dynamic UI handling for role-based and condition-based forecasting.
"""

# Standard library imports
from decimal import ROUND_DOWN, Decimal, InvalidOperation
from functools import cached_property

# Third-party imports (Django)
from django.contrib import messages
from django.core.paginator import Paginator
from django.db import transaction
from django.template.loader import render_to_string

# First party imports (Horilla)
from horilla.auth.mixins import LoginRequiredMixin
from horilla.auth.models import User
from horilla.contrib.core.models import Period, Role
from horilla.contrib.core.utils import get_allowed_user_ids
from horilla.contrib.generics.views import (
    HorillaListView,
    HorillaNavView,
    HorillaSingleDeleteView,
    HorillaSingleFormView,
    HorillaView,
)
from horilla.contrib.utils.middlewares import get_active_company
from horilla.db.models import Q
from horilla.shortcuts import render
from horilla.urls import reverse_lazy
from horilla.utils import timezone
from horilla.utils.decorators import (
    htmx_required,
    method_decorator,
    permission_required,
    permission_required_or_denied,
)
from horilla.utils.translation import gettext_lazy as _
from horilla.views.generic import TemplateView, View
from horilla.web import (
    HttpResponse,
    HttpResponseRedirect,
    HxTriggerResponse,
    ScriptResponse,
)
from horilla_crm.forecast import role_targets

# Local imports
from horilla_crm.forecast.filters import ForecastTargetFilter
from horilla_crm.forecast.forms import ForecastTargetAmountForm, ForecastTargetForm
from horilla_crm.forecast.models import ForecastTarget, ForecastType
from horilla_crm.forecast.utils import get_assignable_target_user_ids


def scope_target_users(request, queryset):
    """Limit ``queryset`` of users to those the requester may set targets for."""
    assignable = get_assignable_target_user_ids(request.user)
    if assignable is None:
        return queryset
    return queryset.filter(pk__in=assignable)


def scope_target_roles(request):
    """Roles the requester may pick: those of the users they can set targets for."""
    assignable = get_assignable_target_user_ids(request.user)
    if assignable is None:
        return Role.objects.all()
    return Role.objects.filter(
        pk__in=User.objects.filter(pk__in=assignable).values("role_id")
    )


def whole_role_requested(data):
    """
    True when the form asks for one total divided among a role's users.

    The role itself is not required here, so the Role Target field shows as soon as
    the switch is on; saving still needs a role.
    """
    return (
        data.get("is_role_based", "off") == "on"
        and data.get("is_whole_role", "off") == "on"
    )


def _to_decimal(value):
    """Parse ``value`` as a non-negative Decimal, or 0 when blank or invalid."""
    try:
        number = Decimal(str(value).strip())
    except (InvalidOperation, ValueError):
        return Decimal("0")
    return number if number > 0 else Decimal("0")


def equal_shares(total, count):
    """Split ``total`` into ``count`` shares to the cent; the last takes the rest."""
    if count <= 0:
        return []
    share = (total / count).quantize(Decimal("0.01"), rounding=ROUND_DOWN)
    shares = [share] * count
    shares[-1] = total - share * (count - 1)
    return shares


def include_below_requested(data):
    """True when the total should cover the chosen role and the roles under it."""
    return whole_role_requested(data) and data.get("include_below", "off") == "on"


def role_split_nodes(request, role_id):
    """
    The chosen role and every role below it that has users the requester may assign.

    Returns a depth-first list of ``{"role_id", "name", "depth", "users"}``; ``depth``
    counts only the roles shown, so a skipped empty role leaves no gap. Users are
    limited to those the requester may set targets for, like everywhere else.
    """
    if not role_id:
        return []
    children, names = {}, {}
    for pk, name, parent_id in Role.objects.values_list(
        "id", "role_name", "parent_role_id"
    ):
        names[pk] = name
        children.setdefault(parent_id, []).append(pk)
    try:
        start = int(role_id)
    except (TypeError, ValueError):
        return []
    if start not in names:
        return []
    for siblings in children.values():
        siblings.sort(key=lambda pk: (str(names[pk]).lower(), pk))

    order, seen = [], set()

    def walk(pk, depth):
        if pk in seen:  # a role cycle must not loop forever
            return
        seen.add(pk)
        order.append((pk, depth))
        for child in children.get(pk, []):
            walk(child, depth + 1)

    walk(start, 0)
    users_by_role = {}
    for user in (
        scope_target_users(
            request,
            User.objects.filter(role_id__in=[pk for pk, _ in order], is_active=True),
        )
        .select_related("role")
        .order_by("first_name", "last_name", "id")
    ):
        users_by_role.setdefault(user.role_id, []).append(user)

    nodes = [
        {
            "role_id": pk,
            "name": names[pk],
            "depth": depth,
            "users": users_by_role[pk],
        }
        for pk, depth in order
        if users_by_role.get(pk)
    ]
    # number the depth by the roles that are shown, so skipped empty roles leave no gap
    stack = []
    for node in nodes:
        while stack and stack[-1] >= node["depth"]:
            stack.pop()
        stack.append(node["depth"])
        node["depth"] = len(stack) - 1
    return nodes


def build_whole_role_context(request, data):
    """
    Context for the whole-role split. Shares start equal; once the requester edits
    one (``wr_manual``), the posted shares are kept.

    By default the total is divided among the users of the chosen role. With
    "Include Roles Below" it is divided by role across the role and every role under
    it: equal per user to start with, so a role with more users gets a larger share.
    """
    role_id = data.get("role") or None
    total = _to_decimal(data.get("wr_amount"))
    manual = data.get("wr_manual") == "1"
    base = {
        "is_whole_role": True,
        "wr_role_selected": bool(role_id),
        "wr_total": total,
        "wr_amount": data.get("wr_amount", ""),
        "wr_manual": "1" if manual else "0",
        "wr_period": data.get("wr_period", ""),
        "wr_type": data.get("wr_type", ""),
    }

    if include_below_requested(data):
        nodes = role_split_nodes(request, role_id)
        all_users = [user for node in nodes for user in node["users"]]
        per_user = dict(
            zip((u.pk for u in all_users), equal_shares(total, len(all_users)))
        )

        # What each user gets. Equal per user to start with. After an edit the browser
        # posts every user's own figure (share_user_<id>), which is then the truth; a
        # post that only carries role figures (share_role_<id>) is divided equally
        # among that role's users.
        shares = dict(per_user)
        if manual:
            if any(f"share_user_{user.pk}" in data for user in all_users):
                shares = {
                    user.pk: _to_decimal(data.get(f"share_user_{user.pk}"))
                    for user in all_users
                }
            else:
                shares = {}
                for node in nodes:
                    role_share = _to_decimal(data.get(f"share_role_{node['role_id']}"))
                    for user, amount in zip(
                        node["users"], equal_shares(role_share, len(node["users"]))
                    ):
                        shares[user.pk] = amount

        role_rows = []
        for node in nodes:
            user_rows = [
                {"user": user, "share": shares[user.pk], "equal": per_user[user.pk]}
                for user in node["users"]
            ]
            role_rows.append(
                {
                    "role_id": node["role_id"],
                    "name": node["name"],
                    "depth": node["depth"],
                    "users": node["users"],
                    "user_rows": user_rows,
                    "user_count": len(user_rows),
                    "share": sum((r["share"] for r in user_rows), Decimal("0")),
                    "equal": sum((r["equal"] for r in user_rows), Decimal("0")),
                }
            )
        shares_sum = sum((row["share"] for row in role_rows), Decimal("0"))
        return {
            **base,
            "wr_mode": "roles",
            "wr_rows": [],
            "wr_role_rows": role_rows,
            "wr_user_count": len(all_users),
            "wr_sum": shares_sum,
            "wr_remaining": total - shares_sum,
        }

    users = (
        list(
            scope_target_users(
                request, User.objects.filter(role_id=role_id, is_active=True)
            ).order_by("first_name", "last_name", "id")
        )
        if role_id
        else []
    )
    equal = equal_shares(total, len(users))
    rows = []
    for index, user in enumerate(users):
        share = _to_decimal(data.get(f"share_{user.pk}")) if manual else equal[index]
        rows.append({"user": user, "share": share, "equal": equal[index]})
    shares_sum = sum((row["share"] for row in rows), Decimal("0"))
    return {
        **base,
        "wr_mode": "users",
        "wr_rows": rows,
        "wr_role_rows": [],
        "wr_sum": shares_sum,
        "wr_remaining": total - shares_sum,
    }


class ForecastTargetScopeMixin:
    """Refuse edit and delete of targets for users outside the requester's hierarchy."""

    def dispatch(self, request, *args, **kwargs):
        """Return the 403 page when the target's user is not assignable."""
        pk = kwargs.get("pk")
        if pk and request.user.is_authenticated:
            assignable = get_assignable_target_user_ids(request.user)
            if assignable is not None:
                owner_id = (
                    ForecastTarget.objects.filter(pk=pk)
                    .values_list("assigned_to_id", flat=True)
                    .first()
                )
                if owner_id is not None and owner_id not in assignable:
                    return render(request, "403.html")
        return super().dispatch(request, *args, **kwargs)


class ForecastTargetView(LoginRequiredMixin, HorillaView):
    """Main forecast target settings page."""

    template_name = "forecast_target/forecast_target_view.html"
    nav_url = reverse_lazy("forecast:forecast_target_nav_view")
    list_url = reverse_lazy("forecast:forecast_target_list_view")
    main_url = reverse_lazy("forecast:forecast_target_view")
    filters_url = reverse_lazy("forecast:forecast_target_filters_view")

    def get(self, request, *args, **kwargs):
        """Validate filter query params and redirect when invalid values are supplied."""
        raw_forecast_type = request.GET.get("forecast_type")
        raw_period = request.GET.get("period")

        def to_int(value):
            try:
                return int(value)
            except (TypeError, ValueError):
                return False

        invalid_params = []
        if raw_forecast_type is not None:
            ft_id = to_int(raw_forecast_type)
            if ft_id is False:
                invalid_params.append(_("Forecast Type"))
            elif not ForecastType.objects.filter(pk=ft_id).exists():
                invalid_params.append(_("Forecast Type"))

        if raw_period is not None:
            p_id = to_int(raw_period)
            if p_id is False:
                invalid_params.append(_("Period"))
            elif not Period.objects.filter(pk=p_id).exists():
                invalid_params.append(_("Period"))

        if invalid_params:
            messages.error(
                request,
                _("Invalid value for: %(params)s.")
                % {"params": ", ".join(str(p) for p in invalid_params)},
            )
            clean_params = {}
            if request.GET.get("section"):
                clean_params["section"] = request.GET["section"]
            query_string = (
                "?" + "&".join(f"{k}={v}" for k, v in clean_params.items())
                if clean_params
                else ""
            )
            return HttpResponseRedirect(str(self.main_url) + query_string)

        return super().get(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        """Build filter context with default forecast type and period selections."""

        context = super().get_context_data(**kwargs)
        company = get_active_company(self.request)

        context["company"] = company
        context["forecast_types"] = ForecastType.objects.all()
        context["has_company"] = bool(company)
        context["has_forecast_types"] = context["forecast_types"].exists()
        context["nav_url"] = self.nav_url
        context["list_url"] = self.list_url
        context["main_url"] = self.main_url
        context["filters_url"] = self.filters_url

        if not company or not context["has_forecast_types"]:
            return context

        forecast_type_id = self.request.GET.get("forecast_type")
        period_id = self.request.GET.get("period")

        if forecast_type_id:
            context["default_forecast_type"] = (
                context["forecast_types"].filter(pk=forecast_type_id).first()
            )
        else:
            context["default_forecast_type"] = context["forecast_types"].first()

        context["periods"] = Period.objects.all()
        current_date = timezone.now().date()

        if period_id:
            context["default_period"] = context["periods"].filter(pk=period_id).first()
        else:
            context["default_period"] = (
                context["periods"]
                .filter(start_date__lte=current_date, end_date__gte=current_date)
                .first()
                or context["periods"].first()
            )

        default_ft = context["default_forecast_type"]
        default_p = context["default_period"]
        context["current_forecast_type_id"] = default_ft.pk if default_ft else None
        context["current_period_id"] = default_p.pk if default_p else None

        return context


@method_decorator(htmx_required, name="dispatch")
@method_decorator(permission_required("forecast.view_forecasttarget"), name="dispatch")
class ForecastTargetFiltersView(LoginRequiredMixin, TemplateView):
    """Load forecast type and period filter dropdowns dynamically."""

    template_name = "forecast_target/forecast_target_filters.html"
    main_url = reverse_lazy("forecast:forecast_target_view")
    list_url = reverse_lazy("forecast:forecast_target_list_view")

    def get_context_data(self, **kwargs):
        """Populate forecast-target filter dropdown context and defaults."""

        context = super().get_context_data(**kwargs)

        forecast_types = ForecastType.objects.all()
        forecast_type_id = self.request.GET.get("forecast_type")
        period_id = self.request.GET.get("period")

        if forecast_type_id:
            default_forecast_type = forecast_types.filter(pk=forecast_type_id).first()
        else:
            default_forecast_type = forecast_types.first()

        periods = Period.objects.all()
        current_date = timezone.now().date()

        if period_id:
            default_period = periods.filter(pk=period_id).first()
        else:
            default_period = (
                periods.filter(
                    start_date__lte=current_date, end_date__gte=current_date
                ).first()
                or periods.first()
            )

        context.update(
            {
                "forecast_types": forecast_types,
                "periods": periods,
                "default_forecast_type": default_forecast_type,
                "default_period": default_period,
                "current_forecast_type_id": forecast_type_id,
                "current_period_id": period_id,
                "main_url": self.main_url,
                "list_url": self.list_url,
            }
        )

        return context


@method_decorator(htmx_required, name="dispatch")
@method_decorator(permission_required("forecast.view_forecasttarget"), name="dispatch")
class ForecastTargetNavbar(LoginRequiredMixin, HorillaNavView):
    """
    Render the forecast target navigation bar with role and condition filters.
    """

    nav_description = _("Set sales targets for your team's forecasts.")
    search_url = reverse_lazy("forecast:forecast_target_list_view")
    main_url = reverse_lazy("forecast:forecast_target_view")
    filterset_class = ForecastTargetFilter
    model_name = "ForecastTarget"
    model_app_label = "forecast"
    nav_width = False
    all_view_types = False
    recently_viewed_option = False
    filter_option = False
    one_view_only = True
    reload_option = False
    border_enabled = False

    @cached_property
    def new_button(self):
        """
        Return a button element for creating a new forecast target.
        """
        if (
            self.request.user.has_perm("forecast.add_forecasttarget")
            and ForecastType.objects.exists()
        ):
            return {
                "url": f"""{reverse_lazy("forecast:forecast_target_form_view")}""",
                "attrs": {"id": "target-create"},
                "title": "Set Target",
            }
        return None


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied("forecast.view_forecasttarget"), name="dispatch"
)
class ForecastTargetListView(LoginRequiredMixin, HorillaListView):
    """
    Foreacst Target List view
    """

    model = ForecastTarget
    view_id = "forecast-target-list"
    filterset_class = ForecastTargetFilter
    search_url = reverse_lazy("forecast:forecast_target_list_view")
    main_url = reverse_lazy("forecast:forecast_target_view")
    save_to_list_option = False
    bulk_select_option = False
    enable_sorting = False

    @cached_property
    def no_record_add_button(self):
        """
        Get the configuration for the "Add" button when no record exist.
        """
        if self.request.user.has_perm("forecast.add_forecasttarget"):
            return {
                "url": f"""{reverse_lazy("forecast:forecast_target_form_view")}""",
                "attrs": 'id="target-create"',
                "title": "Set Target",
            }
        return None

    def get_queryset(self):
        queryset = super().get_queryset()
        forecast_type_id = self.request.GET.get("forecast_type")
        period_id = self.request.GET.get("period")

        if forecast_type_id:
            queryset = queryset.filter(forcasts_type=forecast_type_id)
        if period_id:
            queryset = queryset.filter(period=period_id)

        # Users with only view_own see their own target and their team's
        if get_assignable_target_user_ids(self.request.user) is not None:
            queryset = queryset.filter(
                assigned_to_id__in=get_allowed_user_ids(self.request.user)
            )

        # Targets that belong to a role total are listed above as one row per role
        # total, so they are left out here. While searching they stay, so a person can
        # still be found by name.
        if not self.searching:
            # a target with no additional_info at all is SQL NULL, which a "key is
            # missing" test does not match, so both cases are named
            queryset = queryset.filter(
                Q(additional_info__isnull=True)
                | Q(**{"additional_info__role_target__batch__isnull": True})
            )

        return queryset

    @property
    def searching(self):
        """Whether the list is being searched (then it shows plain user rows)."""
        return bool((self.request.GET.get("search") or "").strip())

    def role_targets_html(self, has_individual=True):
        """The role totals for the chosen type and period, one row each; "" when none."""
        user = self.request.user
        visible = (
            None
            if get_assignable_target_user_ids(user) is None
            else get_allowed_user_ids(user)
        )
        batches = role_targets.list_batches(
            ForecastTarget,
            self.request.GET.get("period") or None,
            self.request.GET.get("forecast_type") or None,
            visible,
        )
        if not batches:
            return ""
        can_change = user.has_perm("forecast.change_forecasttarget")
        for b in batches:
            b["can_edit"] = (
                can_change
                and b["complete"]
                and role_targets.can_change_total(user, ForecastTarget, b["batch"])
            )
        return render_to_string(
            "forecast_target/role_targets_section.html",
            {"batches": batches, "has_individual": has_individual},
            request=self.request,
        )

    def get(self, request, *args, **kwargs):
        """
        Put the role totals above the list of individual targets.

        Only the response that holds the list itself is touched; filter rows, search
        suggestions and the other partials this view can return are left alone.
        """
        response = super().get(request, *args, **kwargs)
        if (
            request.headers.get("HX-Request") == "true"
            and not self.searching
            and getattr(response, "status_code", None) == 200
            and hasattr(response, "content")
            and b'id="forecast-target-list"' in response.content
        ):
            has_individual = self.get_queryset().exists()
            section = self.role_targets_html(has_individual)
            if section and has_individual:
                response.content = section.encode() + response.content
            elif section:
                # only role totals: no empty "Nothing to show" box under them
                response.content = section.encode()
        return response

    def _get_columns(self):
        """
        The columns this user sees.

        A user's layout is saved the first time they open the list, so a column added
        later would never appear for anyone who already uses it, and this page offers no
        column picker to switch it on. The Role Target column is therefore added here
        when the saved layout lacks it. Nothing in the saved layout is rewritten.
        """
        columns = list(super()._get_columns() or [])
        if self.searching:
            if not any(len(c) > 1 and c[1] == "role_target_col" for c in columns):
                columns.append([str(_("Role Target")), "role_target_col"])
            return columns
        # individual targets have no role total, so the column is only for searches
        return [c for c in columns if not (len(c) > 1 and c[1] == "role_target_col")]

    @cached_property
    def columns(self):
        """
        Return the table column headers and their corresponding model fields.
        """

        instance = self.model()
        user_model = instance._meta.get_field("assigned_to").related_model
        return [
            (instance._meta.get_field("assigned_to").verbose_name, "assigned_to"),
            (user_model._meta.get_field("role").verbose_name, "assigned_to__role"),
            (instance._meta.get_field("target_amount").verbose_name, "target_amount"),
            (_("Role Target"), "role_target_col"),
        ]

    actions = [
        {
            "action": "Edit",
            "src": "assets/icons/edit.svg",
            "img_class": "w-4 h-4",
            "permission": "forecast.change_forecasttarget",
            "attrs": """
                        hx-get="{get_edit_url}"
                        hx-target="#modalBox"
                        hx-swap="innerHTML"
                        onclick="openModal()"
                        """,
        },
        {
            "action": "Delete",
            "src": "assets/icons/a4.svg",
            "img_class": "w-4 h-4",
            "permission": "forecast.delete_forecasttarget",
            "attrs": """
                            hx-get="{get_delete_url}"
                            hx-target="#modalBox"
                            hx-swap="innerHTML"
                            onclick="openModal()"
                            """,
        },
    ]


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied("forecast.add_forecasttarget"), name="dispatch"
)
class ForecastTargetFormView(
    ForecastTargetScopeMixin, LoginRequiredMixin, HorillaSingleFormView
):
    """Form view for creating/updating ForecastTarget with dynamic conditions."""

    model = ForecastTarget
    form_class = ForecastTargetForm
    template_name = "forecast_target/forecast_target_form.html"
    form_url = reverse_lazy("forecast:forecast_target_form_view")
    condition_fields = ["assigned_to", "period", "forcasts_type", "target_amount"]
    condition_field_title = _("Select User")
    save_and_new = False

    def _calculate_dynamic_condition_fields(self, request_or_data):
        """
        Calculate condition_fields based on checkbox values.

        The first time the form opens nothing is posted yet; a new target then starts
        with one period and one forecast type for all users and a target per user.
        """
        first_open = (
            self.request.method == "GET" and "is_period_same" not in request_or_data
        )
        default = "on" if first_open else "off"
        is_period_same = request_or_data.get("is_period_same", default) == "on"
        is_target_same = request_or_data.get("is_target_same", "off") == "on"
        is_forecast_type_same = (
            request_or_data.get("is_forecast_type_same", default) == "on"
        )
        fields = ["assigned_to"]
        if not is_period_same:
            fields.append("period")
        if not is_forecast_type_same:
            fields.append("forcasts_type")
        if not is_target_same:
            fields.append("target_amount")
        return fields

    def get_form_kwargs(self):
        """Dynamically set condition_fields based on checkboxes"""
        kwargs = super().get_form_kwargs()
        data = self.request.POST if self.request.method == "POST" else self.request.GET
        kwargs["condition_fields"] = self._calculate_dynamic_condition_fields(data)
        return kwargs

    def get_context_data(self, **kwargs):
        """Add custom context data"""
        context = super().get_context_data(**kwargs)
        if self.request.method == "POST":
            is_role_based = self.request.POST.get("is_role_based", "off") == "on"
            role_id = self.request.POST.get("role")
            if is_role_based:
                users = (
                    User.objects.filter(role_id=role_id)
                    if role_id
                    else User.objects.none()
                )
            else:
                users = User.objects.all()
        else:
            users = User.objects.all()
        context["users"] = scope_target_users(self.request, users)

        if self.request.method == "POST":
            context["condition_fields"] = self._calculate_dynamic_condition_fields(
                self.request.POST
            )
            context["form_submitted"] = True
        else:
            # first open: period and forecast type are chosen once above the rows
            context["condition_fields"] = self._calculate_dynamic_condition_fields(
                self.request.GET
            )
            context["form_submitted"] = False

        context["roles"] = scope_target_roles(self.request)
        context["is_role_based"] = bool(context["form"]["is_role_based"].value())
        if self.request.method == "POST" and whole_role_requested(self.request.POST):
            context.update(build_whole_role_context(self.request, self.request.POST))
        context["period_choices"] = [(p.id, p.name) for p in Period.objects.all()]
        context["forecast_type_choices"] = [
            (f.id, f.name) for f in ForecastType.objects.all()
        ]
        return context

    def form_valid(self, form):
        """Save a whole-role split itself; everything else uses the row flow."""
        if whole_role_requested(self.request.POST) and not self.kwargs.get("pk"):
            return self.save_whole_role(form)
        response = super().form_valid(form)
        if isinstance(response, ScriptResponse) and not self.kwargs.get("pk"):
            latest = (
                ForecastTarget.objects.filter(created_by=self.request.user)
                .order_by("-id")
                .first()
            )
            if latest:
                return self.show_saved(latest.forcasts_type_id, latest.period_id)
        return response

    def show_saved(self, forecast_type_id, period_id):
        """
        Reopen the page on the type and period that was just saved.

        The list would otherwise reload on the old filters, and whoever saved would have
        to pick the type and period again to see what they entered.
        """
        from urllib.parse import parse_qs, urlencode, urlparse

        query = {"forecast_type": forecast_type_id, "period": period_id}
        referer = self.request.META.get("HTTP_REFERER") or ""
        section = parse_qs(urlparse(referer).query).get("section")
        if section:
            query["section"] = section[0]
        response = HttpResponse()
        response["HX-Redirect"] = (
            f"{reverse_lazy('forecast:forecast_target_view')}?{urlencode(query)}"
        )
        return response

    def save_whole_role(self, form):
        """
        Create one target per user from the role total.

        Without "Include Roles Below" the shares are per user. With it the shares are
        still saved per user, but laid out by role: a role's total is the sum of its
        users' shares, and editing a role's total divides it equally among its users
        (the last user takes any rounding remainder). Either way the saved targets add
        up to the role target.
        """
        data = self.request.POST
        context = build_whole_role_context(self.request, data)
        by_role = context["wr_mode"] == "roles"
        errors = []

        # (user, amount) for every target to create
        targets = []
        if by_role:
            for row in context["wr_role_rows"]:
                targets.extend((r["user"], r["share"]) for r in row["user_rows"])
        else:
            targets = [(row["user"], row["share"]) for row in context["wr_rows"]]

        role = (
            scope_target_roles(self.request).filter(pk=data.get("role") or None).first()
        )
        period = Period.objects.filter(pk=data.get("wr_period") or None).first()
        forecast_type = ForecastType.objects.filter(
            pk=data.get("wr_type") or None
        ).first()
        if not role:
            errors.append(_("Select a role you can set targets for."))
        if not period:
            errors.append(_("Period is required."))
        if not forecast_type:
            errors.append(_("Forecast type is required."))
        if context["wr_total"] <= 0:
            errors.append(_("Enter the role target."))
        if not targets:
            errors.append(
                _("No users in this role or the roles below it are available to you.")
                if by_role
                else _("No users in this role are available to you.")
            )
        elif context["wr_remaining"] != 0:
            errors.append(_("Shares must add up to the role target."))

        if period and forecast_type and targets:
            existing = ForecastTarget.objects.filter(
                assigned_to_id__in=[user.pk for user, _amount in targets],
                period=period,
                forcasts_type=forecast_type,
            ).select_related("assigned_to")
            for target in existing:
                errors.append(
                    _("Forecast target already exists for user '%(user)s'.")
                    % {"user": target.assigned_to}
                )

        if errors:
            for error in errors:
                form.add_error(None, error)
            return self.form_invalid(form)

        company = get_active_company(self.request)
        # Every target of this Save carries the same note, so the role total that was
        # entered is remembered and can be checked against what they add up to later.
        batch = role_targets.new_batch_id()
        with transaction.atomic():
            for user, amount in targets:
                ForecastTarget.objects.create(
                    assigned_to=user,
                    # tag each target with the user's own role (the chosen role for a
                    # plain split, where every user belongs to it)
                    role=user.role if by_role else role,
                    period=period,
                    forcasts_type=forecast_type,
                    target_amount=amount,
                    company=company,
                    created_by=self.request.user,
                    updated_by=self.request.user,
                    additional_info=role_targets.stamp(
                        None,
                        batch=batch,
                        role=role,
                        total=context["wr_total"],
                        include_below=by_role,
                        share=amount,
                        user=self.request.user,
                    ),
                )
        self.request.session["condition_row_count"] = 0
        messages.success(
            self.request,
            _("Role target divided among %(count)s users.") % {"count": len(targets)},
        )
        return self.show_saved(forecast_type.pk, period.pk)

    def add_condition_row(self, request):
        """Override to handle dynamic condition_fields and custom context"""
        original_fields = self.condition_fields
        self.condition_fields = self._calculate_dynamic_condition_fields(request.GET)
        try:
            # Calculate new_row_id
            row_id = request.GET.get("row_id", "0")
            if row_id == "next":
                current_count = request.session.get("condition_row_count", 0)
                current_count += 1
                request.session["condition_row_count"] = current_count
                new_row_id = str(current_count)
            else:
                try:
                    new_row_id = str(int(row_id) + 1)
                except ValueError:
                    new_row_id = "1"

            # Temporarily set request for get_form_kwargs
            original_request = self.request
            self.request = request
            form_kwargs = self.get_form_kwargs()
            form_kwargs["row_id"] = new_row_id
            form_kwargs["condition_fields"] = self.condition_fields
            if "pk" in self.kwargs:
                try:
                    form_kwargs["instance"] = self.model.objects.get(
                        pk=self.kwargs["pk"]
                    )
                except self.model.DoesNotExist:
                    pass
            form = self.get_form_class()(**form_kwargs)
            self.request = original_request

            # Filter users
            is_role_based = request.GET.get("is_role_based", "off") == "on"
            role_id = request.GET.get("role")
            users = scope_target_users(
                request,
                (
                    User.objects.filter(role_id=role_id)
                    if is_role_based and role_id
                    else (User.objects.none() if is_role_based else User.objects.all())
                ),
            )

            context = {
                "form": form,
                "condition_fields": self.condition_fields,
                "row_id": new_row_id,
                "submitted_condition_data": self.get_submitted_condition_data(),
                "users": users,
                "period_choices": [(p.id, p.name) for p in Period.objects.all()],
                "forecast_type_choices": [
                    (f.id, f.name) for f in ForecastType.objects.all()
                ],
            }
            return render(request, "forecast_target/condition_row.html", context)
        finally:
            self.condition_fields = original_fields

    def process_row_data_before_create(self, row_data, row_id, form):
        """Process row_data to handle 'same' checkbox logic"""
        if not row_data.get("assigned_to"):
            form.add_error(None, f"User assignment is required for row {row_id}.")
            return False

        # Users with only view_own may set targets for people below them
        assignable = get_assignable_target_user_ids(self.request.user)
        if assignable is not None:
            try:
                chosen = int(row_data.get("assigned_to"))
            except (TypeError, ValueError):
                chosen = None
            if chosen not in assignable:
                form.add_error(
                    None,
                    _("You can only set targets for users below you in the hierarchy."),
                )
                return False

        cleaned = form.cleaned_data
        is_period_same = cleaned.get("is_period_same", False)
        is_target_same = cleaned.get("is_target_same", False)
        is_forecast_type_same = cleaned.get("is_forecast_type_same", False)

        # Handle period
        if is_period_same:
            if not cleaned.get("period"):
                form.add_error(
                    "period",
                    "Period is required when 'Same Period for All' is selected.",
                )
                return False
            row_data["period"] = str(cleaned.get("period").id)
        elif not row_data.get("period"):
            form.add_error(
                None,
                f"Period is required for row {row_id} when 'Same Period for All' is not selected.",
            )
            return False

        # Handle target_amount
        if is_target_same:
            if cleaned.get("target_amount") is None:
                form.add_error(
                    "target_amount",
                    "Target amount is required when 'Same Target for All' is selected.",
                )
                return False
            row_data["target_amount"] = str(cleaned.get("target_amount"))
        elif not row_data.get("target_amount"):
            form.add_error(
                None,
                f"Target amount is required for row {row_id} when 'Same Target for All' is not selected.",
            )
            return False

        # Handle forcasts_type
        if is_forecast_type_same:
            if not cleaned.get("forcasts_type"):
                form.add_error(
                    "forcasts_type",
                    "Forecast type is required when 'Same Forecast Type for All' is selected.",
                )
                return False
            row_data["forcasts_type"] = str(cleaned.get("forcasts_type").id)
        elif not row_data.get("forcasts_type"):
            form.add_error(
                None,
                f"Forecast type is required for row {row_id} when 'Same Forecast Type for All' is not selected.",
            )
            return False

        return row_data  # Return processed row_data

    def check_duplicate_instance(self, row_data, unique_cache, form):
        """Check for duplicate combinations"""
        assigned_to_id = int(row_data.get("assigned_to"))
        period_id = int(row_data.get("period"))
        forcasts_type_id = int(row_data.get("forcasts_type"))

        combination = (assigned_to_id, period_id, forcasts_type_id)
        if combination in unique_cache:
            try:
                user = User.objects.get(id=assigned_to_id)
                return _("Duplicate entry found for user '%(user)s'.") % {"user": user}
            except Exception:
                return str(_("Duplicate entry found."))

        if ForecastTarget.objects.filter(
            assigned_to_id=assigned_to_id,
            period_id=period_id,
            forcasts_type_id=forcasts_type_id,
        ).exists():
            try:
                user = User.objects.get(id=assigned_to_id)
                return _("Forecast target already exists for user '%(user)s'.") % {
                    "user": user
                }
            except Exception:
                return str(_("Forecast target already exists."))

        unique_cache.add(combination)
        return None

    def update_unique_check_cache(self, row_data, unique_cache, instance):
        """Update cache after creating instance"""
        combination = (
            instance.assigned_to_id,
            instance.period_id,
            instance.forcasts_type_id,
        )
        unique_cache.add(combination)

    def modify_create_kwargs(self, create_kwargs, row_data, row_id, form):
        """Modify create_kwargs to handle role based on is_role_based"""
        is_role_based = form.cleaned_data.get("is_role_based", False)
        if not is_role_based:
            create_kwargs["role"] = None
        return create_kwargs


@method_decorator(
    permission_required_or_denied("forecast.change_forecasttarget"), name="dispatch"
)
class ToggleRoleBasedView(View):
    """View to toggle role-based user filtering for forecast target conditions."""

    def post(self, request, *_args, **_kwargs):
        """
        Handle POST request to filter users based on role selection and update condition fields.
        """
        is_role_based = request.POST.get("is_role_based", "off") == "on"
        role_id = request.POST.get("role")
        is_period_same = request.POST.get("is_period_same", "off") == "on"
        is_target_same = request.POST.get("is_target_same", "off") == "on"
        is_forecast_type_same = request.POST.get("is_forecast_type_same", "off") == "on"
        users = User.objects.all()
        if is_role_based:
            if role_id:
                users = users.filter(role_id=role_id)
            else:
                users = User.objects.none()
        users = scope_target_users(request, users)
        form = ForecastTargetForm(request.POST)
        whole_role = (
            build_whole_role_context(request, request.POST)
            if whole_role_requested(request.POST)
            else {}
        )

        condition_fields = ["assigned_to"]
        if not is_period_same:
            condition_fields.append("period")
        if not is_forecast_type_same:
            condition_fields.append("forcasts_type")
        if not is_target_same:
            condition_fields.append("target_amount")

        context = {
            "form": form,
            "condition_fields": condition_fields,
            "users": users,
            "roles": scope_target_roles(request),
            "period_choices": [(p.id, p.name) for p in Period.objects.all()],
            "forecast_type_choices": [
                (f.id, f.name) for f in ForecastType.objects.all()
            ],
            "submitted_condition_data": self.get_condition_data(request),
            "condition_row_count": request.session.get("condition_row_count", 0),
            "is_role_based": is_role_based,
            "form_submitted": False,
            **whole_role,
        }
        return render(
            request,
            "forecast_target/toggle_role_based_response.html",
            context,
        )

    def get_condition_data(self, request):
        """Extract and return condition row data from POST request."""

        possible_condition_fields = [
            "assigned_to",
            "period",
            "target_amount",
            "forcasts_type",
        ]
        condition_data = {}
        for key, value in request.POST.items():
            for field_name in possible_condition_fields:
                if key.startswith(f"{field_name}_") and key != field_name:
                    try:
                        row_id = key.replace(f"{field_name}_", "")
                        if row_id not in condition_data:
                            condition_data[row_id] = {}
                        condition_data[row_id][field_name] = value
                    except Exception:
                        continue
        return condition_data


@method_decorator(
    permission_required_or_denied("forecast.change_forecasttarget"), name="dispatch"
)
class ToggleConditionFieldsView(View):
    """View to dynamically toggle visibility of forecast target condition fields."""

    def post(self, request, *_args, **_kwargs):
        """
        Handle POST request to update visible condition fields based on user selections.
        """
        if whole_role_requested(request.POST):
            # A whole-role split has no per-row fields to toggle
            return HttpResponse(status=204)
        is_period_same = request.POST.get("is_period_same", "off") == "on"
        is_target_same = request.POST.get("is_target_same", "off") == "on"
        is_forecast_type_same = request.POST.get("is_forecast_type_same", "off") == "on"
        is_role_based = request.POST.get("is_role_based", "off") == "on"
        role_id = request.POST.get("role")
        form = ForecastTargetForm(request.POST)

        condition_fields = ["assigned_to"]
        if not is_period_same:
            condition_fields.append("period")
        if not is_forecast_type_same:
            condition_fields.append("forcasts_type")
        if not is_target_same:
            condition_fields.append("target_amount")

        users = User.objects.all()
        if is_role_based:
            if role_id:
                users = users.filter(role_id=role_id)
            else:
                users = User.objects.none()
        users = scope_target_users(request, users)

        # Extract condition data
        possible_condition_fields = [
            "assigned_to",
            "period",
            "target_amount",
            "forcasts_type",
        ]
        condition_data = {}
        for key, value in request.POST.items():
            for field_name in possible_condition_fields:
                if key.startswith(f"{field_name}_") and key != field_name:
                    try:
                        row_id = key.replace(f"{field_name}_", "")
                        if row_id not in condition_data:
                            condition_data[row_id] = {}
                        condition_data[row_id][field_name] = value
                    except Exception:
                        continue

        context = {
            "form": form,
            "condition_fields": condition_fields,
            "users": users,
            "period_choices": [(p.id, p.name) for p in Period.objects.all()],
            "forecast_type_choices": [
                (f.id, f.name) for f in ForecastType.objects.all()
            ],
            "submitted_condition_data": condition_data,
            "condition_row_count": request.session.get("condition_row_count", 0),
            "is_period_same": is_period_same,
            "is_target_same": is_target_same,
            "is_forecast_type_same": is_forecast_type_same,
            "form_submitted": False,
        }
        return render(
            request,
            "forecast_target/toggle_condition_fields_response.html",
            context,
        )


@method_decorator(
    permission_required_or_denied("forecast.change_forecasttarget"), name="dispatch"
)
class UpdateTargetHelpTextView(View):
    """View to update the help text for the target amount based on forecast type."""

    template_name = "forecast_target/target_amount_help_text.html"

    def post(self, request, *_args, **_kwargs):
        """
        Update and return the help text for the target amount based on forecast type.
        """
        row_id = request.GET.get("row_id", "0")
        forecast_type_id = (
            request.POST.get("forcasts_type")
            or request.POST.get(f"forcasts_type_{row_id}")
            or request.POST.get("forcasts_type_0")
        )
        help_text = _("Enter the target amount")

        if forecast_type_id:
            try:
                forecast_type = ForecastType.objects.get(id=forecast_type_id)
                if forecast_type.is_quantity_based:
                    help_text = _("Enter the quantity")
                elif forecast_type.is_revenue_based:
                    help_text = _("Enter the revenue amount")
            except ForecastType.DoesNotExist:
                pass

        context = {
            "help_text": help_text,
            "row_id": row_id,
        }
        return render(request, self.template_name, context)


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied("forecast.change_forecasttarget"), name="dispatch"
)
class UpdateForecastTarget(
    ForecastTargetScopeMixin, LoginRequiredMixin, HorillaSingleFormView
):
    """View to update the target amount for a specific ForecastTarget."""

    model = ForecastTarget
    form_class = ForecastTargetAmountForm
    fields = ["target_amount"]
    modal_height = False
    template_name = "forecast_target/target_update_form.html"

    @property
    def full_width_fields(self):
        """
        Target spans the form, unless "Also Change the Role Total" sits beside it.

        That switch only exists for a target inside a role total, when the person
        editing may change the total; otherwise Target is the only field.
        """
        target = ForecastTarget.objects.filter(pk=self.kwargs.get("pk")).first()
        note = role_targets.note_of(target) if target else None
        if note and role_targets.can_change_total(
            self.request.user, ForecastTarget, note["batch"]
        ):
            return []
        return ["target_amount"]

    def get_context_data(self, **kwargs):
        """Add the role total this target belongs to (if any) for the comparison note."""
        context = super().get_context_data(**kwargs)
        instance = context["form"].instance
        status = role_targets.status_of(instance) if instance.pk else None
        context["role_target_status"] = status
        if status:
            # what the role's other targets add up to, without this one
            context["role_target_others"] = status["current"] - instance.target_amount
        return context

    def form_valid(self, form):
        """
        Save the amount, then deal with the role total it belongs to, if any.

        With "Also Change the Role Total" on, the role total becomes what the role's
        targets now add up to, for every target of that role total. Otherwise the role
        total stays as set, and a warning says so when it no longer adds up.
        """
        follow = form.cleaned_data.get("update_role_total")
        response = super().form_valid(form)
        note = role_targets.note_of(self.object)
        if not note:
            return response

        if follow:
            new_total = role_targets.current_sum(ForecastTarget, note["batch"])
            role_targets.change_total(
                ForecastTarget, note["batch"], new_total, self.request.user
            )
            messages.success(
                self.request,
                _("The %(role)s role target is now %(total)s.")
                % {
                    "role": note.get("role_name") or "",
                    "total": role_targets.money(new_total),
                },
            )
            return response

        status = role_targets.status_of(self.object)
        if status and not status["matches"]:
            messages.warning(
                self.request,
                _(
                    "This target is part of the %(role)s role target of %(total)s. "
                    "The targets of that role now add up to %(current)s."
                )
                % {
                    "role": status["role_name"],
                    "total": role_targets.money(status["total"]),
                    "current": role_targets.money(status["current"]),
                },
            )
        return response

    @cached_property
    def form_url(self):
        """
        Return the URL for the update form of the specific ForecastTarget instance.
        """
        pk = self.kwargs.get("pk") or self.request.GET.get("id")
        if pk:
            return reverse_lazy(
                "forecast:forecast_target_update_form_view", kwargs={"pk": pk}
            )
        return None


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied("forecast.delete_forecasttarget", modal=True),
    name="dispatch",
)
class ForecastTargetDeleteView(
    ForecastTargetScopeMixin, LoginRequiredMixin, HorillaSingleDeleteView
):
    """View to delete a ForecastTarget and handle the post-delete response."""

    model = ForecastTarget

    def get_post_delete_response(self):
        """After deleting, say so when the role's targets no longer add up to its total."""
        status = role_targets.status_of(self.object)
        if status and not status["matches"]:
            messages.warning(
                self.request,
                _(
                    "The %(role)s role target is %(total)s, but its targets now add "
                    "up to %(current)s."
                )
                % {
                    "role": status["role_name"],
                    "total": role_targets.money(status["total"]),
                    "current": role_targets.money(status["current"]),
                },
            )
        return HxTriggerResponse()


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied("forecast.view_forecasttarget"), name="dispatch"
)
class ForecastRoleTargetUsersView(LoginRequiredMixin, TemplateView):
    """
    One page of the users (with their targets) behind a role total.

    Opened from a role total's row in the target list. The first page comes back as a
    nested table under that row; later pages are just more rows. A user who may only
    see part of the team sees only those users.
    """

    template_name = "forecast_target/role_target_users.html"
    PER_PAGE = 20

    def get_context_data(self, **kwargs):
        """Load the requested page of targets for the role total."""
        context = super().get_context_data(**kwargs)
        batch = self.request.GET.get("batch") or ""
        context.update(
            {"batch": batch, "targets": [], "has_next": False, "page_number": 1}
        )
        if not batch.isalnum():
            return context
        queryset = ForecastTarget.objects.filter(
            is_active=True, **{"additional_info__role_target__batch": batch}
        ).select_related("assigned_to", "assigned_to__role")
        if get_assignable_target_user_ids(self.request.user) is not None:
            queryset = queryset.filter(
                assigned_to_id__in=get_allowed_user_ids(self.request.user)
            )
        # roles in hierarchy order (top role first, each role's users together)
        first = queryset.first()
        note = role_targets.note_of(first) if first else None
        depth_of, rank_of = {}, {}
        if note and note.get("role_id"):
            nodes = role_split_nodes(self.request, note["role_id"])
            for index, node in enumerate(nodes):
                depth_of[node["role_id"]] = node["depth"]
                rank_of[node["role_id"]] = index
        if rank_of:
            from django.db.models import Case, IntegerField, Value, When

            queryset = queryset.annotate(
                role_rank=Case(
                    *[
                        When(assigned_to__role_id=r, then=Value(i))
                        for r, i in rank_of.items()
                    ],
                    default=Value(len(rank_of)),
                    output_field=IntegerField(),
                )
            ).order_by(
                "role_rank", "assigned_to__first_name", "assigned_to__last_name", "id"
            )
        else:
            queryset = queryset.order_by(
                "assigned_to__first_name", "assigned_to__last_name", "id"
            )
        try:
            number = max(int(self.request.GET.get("page", 1)), 1)
        except ValueError:
            number = 1
        paginator = Paginator(queryset, self.PER_PAGE)
        page = paginator.get_page(number)
        from django.db.models import Count, Sum

        role_totals = {
            r["assigned_to__role_id"]: r
            for r in queryset.order_by()
            .values("assigned_to__role_id")
            .annotate(total=Sum("target_amount"), users=Count("id"))
        }
        rows, previous = [], self.request.GET.get("prev") or ""
        for t in page.object_list:
            role_id = t.assigned_to.role_id
            rows.append(
                {
                    "target": t,
                    "new_role": str(role_id) != previous,
                    "role_total": role_totals.get(role_id),
                    "depth": depth_of.get(role_id, 0),
                    "indent": 1 + 1.25 * depth_of.get(role_id, 0),
                    "user_indent": 2.25 + 1.25 * depth_of.get(role_id, 0),
                }
            )
            previous = str(role_id)
        context.update(
            {
                "actions": ForecastTargetListView.actions,
                "can_edit_total": self.request.user.has_perm(
                    "forecast.change_forecasttarget"
                )
                and role_targets.can_change_total(
                    self.request.user, ForecastTarget, batch
                ),
                "rows": rows,
                "last_role": previous,
                "targets": page.object_list,
                "page_number": page.number,
                "has_next": page.has_next(),
                "next_page": page.next_page_number() if page.has_next() else None,
                "total_users": paginator.count,
            }
        )
        return context


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied("forecast.change_forecasttarget"), name="dispatch"
)
class ForecastRoleTotalEditView(LoginRequiredMixin, TemplateView):
    """
    Change a role total from its row in the target list.

    Every user's target is scaled by the same factor, so the targets keep adding up to
    the new total and any unequal split stays proportionally unequal.
    """

    template_name = "forecast_target/role_total_form.html"

    def _batch_info(self, request):
        """The role total being edited, or ``None`` when it is missing or not allowed."""
        batch = request.GET.get("batch") or request.POST.get("batch") or ""
        if not batch.isalnum():
            return None
        if not role_targets.can_change_total(request.user, ForecastTarget, batch):
            return None
        for info in role_targets.list_batches(ForecastTarget):
            if info["batch"] == batch:
                return self._for_role(request, info)
        return None

    def _for_role(self, request, info):
        """The whole role total, or just one role inside it when ``role`` is given."""
        role_id = request.GET.get("role") or request.POST.get("role")
        if not role_id:
            return info
        try:
            role_id = int(role_id)
        except ValueError:
            return None
        from django.db.models import Sum

        rows = ForecastTarget.objects.filter(
            is_active=True,
            assigned_to__role_id=role_id,
            **{"additional_info__role_target__batch": info["batch"]},
        )
        count = rows.count()
        if not count:
            return None
        role = Role.objects.filter(pk=role_id).first()
        total = rows.aggregate(s=Sum("target_amount"))["s"]
        return dict(
            info,
            role_id=role_id,
            role_name=role.role_name if role else info["role_name"],
            total=total,
            current=total,
            members=count,
            single_role=True,
        )

    def get(self, request, *args, **kwargs):
        """Show the form with the current total filled in."""
        info = self._batch_info(request)
        if not info:
            return HttpResponse(status=403)
        return render(request, self.template_name, {"b": info})

    def post(self, request, *args, **kwargs):
        """Scale the users' targets to the new total."""
        info = self._batch_info(request)
        if not info:
            return HttpResponse(status=403)
        try:
            new_total = _to_decimal(request.POST.get("total"))
        except Exception:
            new_total = None
        if not new_total or new_total <= 0:
            return render(
                request,
                self.template_name,
                {"b": info, "error": _("Enter a role target greater than zero.")},
            )
        count = role_targets.rescale_total(
            ForecastTarget,
            info["batch"],
            new_total,
            request.user,
            role_id=info.get("role_id") if info.get("single_role") else None,
        )
        messages.success(
            request,
            _("%(role)s role target changed to %(total)s for %(count)s users.")
            % {"role": info["role_name"], "total": new_total, "count": count},
        )
        return ScriptResponse(close=True, reload=True)
