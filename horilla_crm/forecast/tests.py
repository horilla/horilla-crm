"""Tests for forecast access scoped by the role hierarchy."""

# Standard library imports
from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from unittest import mock

# Third-party imports (Django)
from django.contrib.auth.models import Permission
from django.contrib.auth.signals import user_logged_in, user_logged_out
from django.http import HttpResponse
from django.test import RequestFactory, TestCase
from django.views import View
from login_history.models import post_login, post_logout

# First party imports (Horilla)
from horilla.auth.models import User
from horilla.contrib.core.models import (
    Company,
    FiscalYear,
    FiscalYearInstance,
    Period,
    Quarter,
    Role,
)

# Local imports
from horilla_crm.forecast import role_targets
from horilla_crm.forecast.models import Forecast, ForecastTarget, ForecastType
from horilla_crm.forecast.utils import (
    build_forecast_role_tree,
    get_assignable_target_user_ids,
    get_forecast_owner_scope,
    resolve_forecast_scope,
)
from horilla_crm.forecast.views.core.helpers import ForecastTypeTabHelpersMixin
from horilla_crm.forecast.views.core.mixins import ForecastTypeTabMixin
from horilla_crm.forecast.views.forecast_target import (
    ForecastTargetFormView,
    ForecastTargetScopeMixin,
    build_whole_role_context,
    equal_shares,
    role_split_nodes,
    scope_target_roles,
    scope_target_users,
)


class HierarchyFixture(TestCase):
    """Shared users for the forecast scope tests (defines no tests itself).

    Hierarchy: Head > Manager > Rep, with Peer in an unrelated role. Everyone
    except the superuser and ``viewer`` has only ``view_own_opportunity``.
    """

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # django-login-history reads request.META['HTTP_USER_AGENT'] on login
        user_logged_in.disconnect(post_login)
        user_logged_out.disconnect(post_logout)

    @classmethod
    def tearDownClass(cls):
        user_logged_in.connect(post_login)
        user_logged_out.connect(post_logout)
        super().tearDownClass()

    def setUp(self):
        self.company = Company.objects.create(
            name="Acme", email="acme@example.com", country="US"
        )
        head_role = Role.objects.create(role_name="Head", company=self.company)
        manager_role = Role.objects.create(
            role_name="Manager", parent_role=head_role, company=self.company
        )
        rep_role = Role.objects.create(
            role_name="Rep", parent_role=manager_role, company=self.company
        )
        other_role = Role.objects.create(role_name="Other", company=self.company)
        self.head = self.make_user("head", head_role)
        self.manager = self.make_user("manager", manager_role)
        self.rep = self.make_user("rep", rep_role)
        self.rep2 = self.make_user("rep2", rep_role)
        self.peer = self.make_user("peer", other_role)
        self.viewer = self.make_user("viewer", other_role, perm="view_opportunity")
        self.nobody = User.objects.create_user(
            username="nobody",
            email="nobody@example.com",
            password="pass",
            company=self.company,
        )
        self.superuser = User.objects.create_superuser(
            username="root", email="root@example.com", password="pass"
        )

    def make_user(self, username, role, perm="view_own_opportunity"):
        """Create a user in ``role`` holding a single forecast permission."""
        user = User.objects.create_user(
            username=username,
            email=f"{username}@example.com",
            password="pass",
            company=self.company,
            role=role,
        )
        user.user_permissions.add(
            Permission.objects.get(
                content_type__app_label="opportunities", codename=perm
            )
        )
        return user


class ForecastScopeTests(HierarchyFixture):
    """Who may see whose forecast."""

    def test_view_all_and_superuser_are_unrestricted(self):
        """view_opportunity and superusers get no owner filter at all."""
        self.assertIsNone(get_forecast_owner_scope(self.viewer))
        self.assertIsNone(get_forecast_owner_scope(self.superuser))

    def test_manager_sees_self_and_subordinates(self):
        """A manager's scope covers the reps below them and nobody else."""
        self.assertEqual(
            get_forecast_owner_scope(self.manager),
            {self.manager.pk, self.rep.pk, self.rep2.pk},
        )

    def test_head_sees_every_level_below(self):
        """The scope is recursive through the role tree."""
        self.assertEqual(
            get_forecast_owner_scope(self.head),
            {self.head.pk, self.manager.pk, self.rep.pk, self.rep2.pk},
        )

    def test_user_without_subordinates_sees_only_self(self):
        """No team means exactly today's behavior."""
        self.assertEqual(get_forecast_owner_scope(self.rep), {self.rep.pk})
        self.assertEqual(get_forecast_owner_scope(self.peer), {self.peer.pk})

    def test_no_forecast_permission_sees_nothing(self):
        """Without either permission the scope is empty."""
        self.assertEqual(get_forecast_owner_scope(self.nobody), set())

    def test_resolve_combines_a_team_when_no_user_is_chosen(self):
        """A manager with no user_id gets the combined team view."""
        owner_ids, user_id, allowed = resolve_forecast_scope(self.manager, None)
        self.assertTrue(allowed)
        self.assertIsNone(user_id)
        self.assertEqual(owner_ids, {self.manager.pk, self.rep.pk, self.rep2.pk})

    def test_resolve_defaults_to_self_without_a_team(self):
        """A rep with no user_id is pinned to their own forecast."""
        owner_ids, user_id, allowed = resolve_forecast_scope(self.rep, None)
        self.assertTrue(allowed)
        self.assertEqual(user_id, str(self.rep.pk))
        self.assertEqual(owner_ids, {self.rep.pk})

    def test_resolve_allows_a_subordinate(self):
        """A manager may pick one of their reps."""
        _, user_id, allowed = resolve_forecast_scope(self.manager, self.rep.pk)
        self.assertTrue(allowed)
        self.assertEqual(user_id, str(self.rep.pk))

    def test_resolve_rejects_users_outside_the_hierarchy(self):
        """Boss, peer and other branches are all forbidden, as is junk input."""
        for requested in (self.head.pk, self.peer.pk, "abc", 999999):
            _, _, allowed = resolve_forecast_scope(self.manager, requested)
            self.assertFalse(allowed, requested)
        _, _, allowed = resolve_forecast_scope(self.rep, self.rep2.pk)
        self.assertFalse(allowed)

    def test_resolve_leaves_view_all_unchanged(self):
        """Admins may pick anyone, or nobody for the combined view."""
        owner_ids, user_id, allowed = resolve_forecast_scope(self.superuser, None)
        self.assertEqual((owner_ids, user_id, allowed), (None, None, True))
        _, user_id, allowed = resolve_forecast_scope(self.viewer, self.peer.pk)
        self.assertEqual((user_id, allowed), (str(self.peer.pk), True))

    def test_resolve_rejects_users_without_permission(self):
        """No forecast permission means every request is refused."""
        _, _, allowed = resolve_forecast_scope(self.nobody, None)
        self.assertFalse(allowed)


class ForecastNavbarViewTests(HierarchyFixture):
    """The navbar user filter reflects the scope."""

    def get_navbar(self, user, **params):
        """Render the navbar as ``user`` and return the response."""
        from django.urls import reverse

        self.client.force_login(user)
        return self.client.get(
            reverse("forecast:forecast_navbar_view"),
            params,
            HTTP_HX_REQUEST="true",
        )

    def test_manager_gets_a_team_filter(self):
        """A manager's user list holds their reports, not other branches."""
        response = self.get_navbar(self.manager)
        self.assertEqual(response.status_code, 200)
        users = set(response.context["users"].values_list("pk", flat=True))
        self.assertEqual(users, {self.manager.pk, self.rep.pk, self.rep2.pk})
        self.assertTrue(response.context["show_all_users_option"])

    def test_rep_gets_no_filter(self):
        """A user without a team keeps the single-user navbar."""
        response = self.get_navbar(self.rep)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.context["show_all_users_option"])
        self.assertEqual(
            list(response.context["users"].values_list("pk", flat=True)),
            [self.rep.pk],
        )

    def test_view_all_still_lists_everyone(self):
        """Admins keep the company-wide list."""
        response = self.get_navbar(self.superuser)
        self.assertTrue(response.context["show_all_users_option"])
        self.assertGreaterEqual(response.context["users"].count(), 7)


class TargetScopeTests(HierarchyFixture):
    """Who may set, edit and see forecast targets."""

    def request_as(self, user):
        """Return a GET request authenticated as ``user``."""
        request = RequestFactory().get("/")
        request.user = user
        return request

    def test_unrestricted_users_can_set_any_target(self):
        """Superusers, view-all users and users with no forecast permission."""
        for user in (self.superuser, self.viewer, self.nobody):
            self.assertIsNone(get_assignable_target_user_ids(user), user)

    def test_manager_sets_targets_for_reports_only(self):
        """Never for themselves, a peer, or the boss."""
        self.assertEqual(
            get_assignable_target_user_ids(self.manager),
            {self.rep.pk, self.rep2.pk},
        )
        self.assertEqual(
            get_assignable_target_user_ids(self.head),
            {self.manager.pk, self.rep.pk, self.rep2.pk},
        )

    def test_user_without_a_team_sets_no_targets(self):
        """A rep has nobody below them."""
        self.assertEqual(get_assignable_target_user_ids(self.rep), set())

    def test_user_picker_is_limited_to_reports(self):
        """The Select User list shows only people the manager may assign."""
        users = scope_target_users(self.request_as(self.manager), User.objects.all())
        self.assertEqual(
            set(users.values_list("pk", flat=True)), {self.rep.pk, self.rep2.pk}
        )
        everyone = scope_target_users(
            self.request_as(self.superuser), User.objects.all()
        )
        self.assertEqual(everyone.count(), User.objects.count())

    def test_role_picker_is_limited_to_roles_below(self):
        """Only the Rep role is offered to the manager."""
        roles = scope_target_roles(self.request_as(self.manager))
        self.assertEqual(set(roles.values_list("role_name", flat=True)), {"Rep"})

    def guarded_view(self):
        """A bare view guarded by the same mixin as the edit and delete views."""

        class Guarded(ForecastTargetScopeMixin, View):
            """Returns 200 when the mixin lets the request through."""

            def get(self, request, *args, **kwargs):
                return HttpResponse("ok")

        return Guarded.as_view()

    def status_for(self, user, owner):
        """403 when ``user`` is sent to the 403 page for ``owner``'s target, else 200."""
        request = self.request_as(user)
        with mock.patch.object(
            ForecastTarget.objects, "filter"
        ) as target_filter, mock.patch(
            "horilla_crm.forecast.views.forecast_target.render",
            return_value=HttpResponse("denied", status=403),
        ):
            target_filter.return_value.values_list.return_value.first.return_value = (
                owner.pk
            )
            return self.guarded_view()(request, pk=1).status_code

    def test_edit_and_delete_are_refused_outside_the_hierarchy(self):
        """A manager can open a report's target, not their own, a peer's or the boss's."""
        self.assertEqual(self.status_for(self.manager, self.rep), 200)
        self.assertEqual(self.status_for(self.manager, self.manager), 403)
        self.assertEqual(self.status_for(self.manager, self.head), 403)
        self.assertEqual(self.status_for(self.manager, self.peer), 403)

    def test_edit_and_delete_unchanged_for_admins(self):
        """No restriction for superusers or view-all users."""
        self.assertEqual(self.status_for(self.superuser, self.head), 200)
        self.assertEqual(self.status_for(self.viewer, self.peer), 200)


class WholeRoleTargetTests(HierarchyFixture):
    """One total for a role, divided among its users."""

    def setUp(self):
        super().setUp()
        # Three reps in one role, so a split has something to divide
        self.rep3 = self.make_user("rep3", self.rep.role)
        self.fiscal_year, _ = FiscalYear.objects.get_or_create(company=self.company)
        instance = FiscalYearInstance.objects.create(
            fiscal_year_config=self.fiscal_year,
            start_date=date(2026, 1, 1),
            end_date=date(2026, 12, 31),
            name="FY 2026",
            company=self.company,
        )
        quarter = Quarter.objects.create(
            fiscal_year=instance,
            name="Q1",
            quarter_number=1,
            start_date=date(2026, 1, 1),
            end_date=date(2026, 3, 31),
            company=self.company,
        )
        self.period = Period.objects.create(
            quarter=quarter,
            name="Period 1",
            period_number=1,
            start_date=date(2026, 1, 1),
            end_date=date(2026, 1, 31),
            company=self.company,
        )
        self.forecast_type = ForecastType.objects.create(
            name="Revenue", company=self.company
        )

    def post_data(self, shares=None, **overrides):
        """POST data for a whole-role split of 90 over the Rep role."""
        data = {
            "is_role_based": "on",
            "is_whole_role": "on",
            "role": str(self.rep.role_id),
            "wr_amount": "90",
            "wr_period": str(self.period.pk),
            "wr_type": str(self.forecast_type.pk),
        }
        for user_id, value in (shares or {}).items():
            data[f"share_{user_id}"] = value
        if shares:
            data["wr_manual"] = "1"
        data.update(overrides)
        return data

    def request_as(self, user, data):
        """POST request authenticated as ``user``."""
        request = RequestFactory().post("/", data)
        request.user = user
        return request

    def test_equal_shares_add_up_to_the_cent(self):
        """The last user takes the rounding remainder."""
        self.assertEqual(
            equal_shares(Decimal("100"), 3), [Decimal("33.33")] * 2 + [Decimal("33.34")]
        )
        self.assertEqual(equal_shares(Decimal("90"), 3), [Decimal("30.00")] * 3)
        self.assertEqual(equal_shares(Decimal("5"), 0), [])

    def test_context_splits_equally_by_default(self):
        """Admins see every user in the role with an equal share."""
        context = build_whole_role_context(
            self.request_as(self.superuser, self.post_data()), self.post_data()
        )
        shares = {row["user"].pk: row["share"] for row in context["wr_rows"]}
        self.assertEqual(
            shares,
            {
                self.rep.pk: Decimal("30"),
                self.rep2.pk: Decimal("30"),
                self.rep3.pk: Decimal("30"),
            },
        )
        self.assertEqual(context["wr_remaining"], 0)

    def test_context_keeps_edited_shares_and_reports_remaining(self):
        """Uneven shares are kept; what is left over is reported."""
        data = self.post_data(
            shares={self.rep.pk: "50", self.rep2.pk: "20", self.rep3.pk: "10"}
        )
        context = build_whole_role_context(self.request_as(self.superuser, data), data)
        self.assertEqual(context["wr_sum"], Decimal("80"))
        self.assertEqual(context["wr_remaining"], Decimal("10"))

    def test_context_lists_only_users_the_manager_may_assign(self):
        """A manager's split covers their reports, never their own role."""
        data = self.post_data(role=str(self.manager.role_id))
        context = build_whole_role_context(self.request_as(self.manager, data), data)
        self.assertEqual(context["wr_rows"], [])

    def save_as(self, user, data):
        """Run the whole-role save as ``user``; return (response, form errors)."""
        view = ForecastTargetFormView()
        request = self.request_as(user, data)
        request.session = {}
        request._messages = mock.MagicMock()
        view.request = request
        view.kwargs = {}
        form = mock.MagicMock()
        errors = []
        form.add_error.side_effect = lambda field, message: errors.append(str(message))
        with mock.patch.object(
            ForecastTargetFormView, "form_invalid", return_value="invalid"
        ):
            response = view.save_whole_role(form)
        return response, errors

    def test_save_creates_a_target_per_user(self):
        """Equal split: one target per user, tagged with the role."""
        response, errors = self.save_as(self.superuser, self.post_data())
        self.assertEqual(errors, [])
        self.assertNotEqual(response, "invalid")
        targets = ForecastTarget.objects.filter(period=self.period)
        self.assertEqual(targets.count(), 3)
        self.assertEqual({t.target_amount for t in targets}, {Decimal("30")})
        self.assertEqual({t.role_id for t in targets}, {self.rep.role_id})

    def test_save_keeps_an_uneven_split(self):
        """Edited shares are saved as entered."""
        data = self.post_data(
            shares={self.rep.pk: "50", self.rep2.pk: "25", self.rep3.pk: "15"}
        )
        self.save_as(self.superuser, data)
        saved = {
            t.assigned_to_id: t.target_amount
            for t in ForecastTarget.objects.filter(period=self.period)
        }
        self.assertEqual(
            saved,
            {
                self.rep.pk: Decimal("50"),
                self.rep2.pk: Decimal("25"),
                self.rep3.pk: Decimal("15"),
            },
        )

    def test_save_refuses_shares_that_do_not_add_up(self):
        """Nothing is created when the shares miss the role total."""
        data = self.post_data(
            shares={self.rep.pk: "50", self.rep2.pk: "20", self.rep3.pk: "10"}
        )
        response, errors = self.save_as(self.superuser, data)
        self.assertEqual(response, "invalid")
        self.assertIn("Shares must add up to the role target.", errors)
        self.assertFalse(ForecastTarget.objects.exists())

    def test_save_refuses_an_existing_target(self):
        """A user who already has this period and type is not overwritten."""
        ForecastTarget.objects.create(
            assigned_to=self.rep,
            period=self.period,
            forcasts_type=self.forecast_type,
            target_amount=1,
            company=self.company,
        )
        response, errors = self.save_as(self.superuser, self.post_data())
        self.assertEqual(response, "invalid")
        self.assertEqual(ForecastTarget.objects.count(), 1)
        self.assertTrue(any("already exists" in e for e in errors))

    def test_manager_cannot_split_their_own_role(self):
        """The role is not offered, so the save is refused."""
        data = self.post_data(role=str(self.manager.role_id))
        response, errors = self.save_as(self.manager, data)
        self.assertEqual(response, "invalid")
        self.assertFalse(ForecastTarget.objects.exists())

    def test_manager_can_split_a_role_below_them(self):
        """A manager divides a total among their reports."""
        response, errors = self.save_as(self.manager, self.post_data())
        self.assertEqual(errors, [])
        self.assertEqual(ForecastTarget.objects.filter(period=self.period).count(), 3)

    def test_role_target_field_shows_before_a_role_is_chosen(self):
        """Switching the whole-role option on shows the amount field straight away."""
        from django.urls import reverse

        self.client.force_login(self.superuser)
        response = self.client.post(
            reverse("forecast:toggle_role_based"),
            {"is_role_based": "on", "is_whole_role": "on"},
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(response.status_code, 200)
        html = response.content.decode()
        self.assertIn('name="wr_amount"', html)
        self.assertIn("Select a role to split the target among its users.", html)

    def test_no_role_means_no_users_to_split_yet(self):
        """Without a role the split lists nobody, and the form says why."""
        data = self.post_data(role="")
        context = build_whole_role_context(self.request_as(self.superuser, data), data)
        self.assertEqual(context["wr_rows"], [])
        self.assertFalse(context["wr_role_selected"])

    def test_save_without_a_role_is_refused(self):
        """A total with no role has nobody to go to, so nothing is created."""
        response, errors = self.save_as(self.superuser, self.post_data(role=""))
        self.assertEqual(response, "invalid")
        self.assertIn("Select a role you can set targets for.", errors)
        self.assertFalse(ForecastTarget.objects.exists())


class ForecastTargetFormRenderTests(HierarchyFixture):
    """The Create Forecast Target form renders on the generic single form shell."""

    def get_form(self, user):
        """Open the create form as ``user`` the way the Set Target button does."""
        from django.urls import reverse

        self.client.force_login(user)
        return self.client.get(
            reverse("forecast:forecast_target_form_view"), HTTP_HX_REQUEST="true"
        )

    def test_form_uses_the_generic_shell_and_target_fields(self):
        """Shell from single_form_view.html; switches and rows from the target template."""
        response = self.get_form(self.superuser)
        self.assertEqual(response.status_code, 200)
        names = [t.name for t in response.templates]
        self.assertIn("single_form_view.html", names)
        self.assertIn("forecast_target/forecast_target_form.html", names)
        html = response.content.decode()
        self.assertIn("single-form-save-spinner", html)
        self.assertIn('id="condition-fields-container"', html)
        self.assertIn("Role-Based Assignment", html)
        self.assertIn("Same Period for All", html)
        self.assertIn("Same Target for All", html)
        # Switches use the generic form's segmented Yes/No control
        self.assertEqual(html.count('class="flex flex-col w-full" data-bool-field'), 4)
        self.assertNotIn("peer-checked:bg-primary-600", html)

    def test_form_is_posted_back_to_itself(self):
        """The shell posts to the form URL and swaps the form in place."""
        html = self.get_form(self.superuser).content.decode()
        self.assertIn('hx-post="/crm/forecast/forecast-target-form-view/', html)
        self.assertIn('hx-swap="outerHTML"', html)

    def test_manager_form_lists_only_their_reports(self):
        """The user picker in the rows is limited to people below the manager."""
        self.manager.user_permissions.add(
            Permission.objects.get(
                content_type__app_label="forecast", codename="add_forecasttarget"
            )
        )
        response = self.get_form(self.manager)
        self.assertEqual(response.status_code, 200)
        users = set(response.context["users"].values_list("pk", flat=True))
        self.assertEqual(users, {self.rep.pk, self.rep2.pk})


class ForecastRoleTreeTests(TestCase):
    """How the role hierarchy is laid out for the forecast table."""

    ROLES = [
        (1, "Head", None),
        (2, "Manager", 1),
        (3, "Rep", 2),
        (4, "Support", 1),
        (5, "Other", None),
    ]

    def layout(self, counts):
        """(name, depth, users, subtree) for each node, top to bottom."""
        return [
            (n["name"], n["depth"], n["user_count"], n["subtree_ids"])
            for n in build_forecast_role_tree(self.ROLES, counts)
        ]

    def test_admin_sees_the_whole_hierarchy_in_order(self):
        """Children sit under their parent, and users without a role come last."""
        nodes = self.layout({1: 1, 2: 2, 3: 5, 4: 1, 5: 3, None: 2})
        self.assertEqual(
            nodes,
            [
                ("Head", 0, 9, [1, 2, 3, 4]),
                ("Manager", 1, 7, [2, 3]),
                ("Rep", 2, 5, [3]),
                ("Support", 1, 1, [4]),
                ("Other", 0, 3, [5]),
                (None, 0, 2, [None]),
            ],
        )

    def test_a_managers_view_starts_at_their_own_role(self):
        """Empty roles above the manager are skipped, not shown as empty rows."""
        nodes = self.layout({2: 1, 3: 5})
        self.assertEqual(nodes, [("Manager", 0, 6, [2, 3]), ("Rep", 1, 5, [3])])

    def test_has_children_marks_collapsible_rows(self):
        """Only roles with a shown role below them get a toggle."""
        nodes = build_forecast_role_tree(self.ROLES, {1: 1, 2: 2, 3: 5})
        flags = {n["name"]: n["has_children"] for n in nodes}
        self.assertEqual(flags, {"Head": True, "Manager": True, "Rep": False})

    def test_a_role_cycle_does_not_loop_forever(self):
        """Bad data (A under B under A) still returns."""
        nodes = build_forecast_role_tree([(1, "A", 2), (2, "B", 1)], {1: 1, 2: 1})
        self.assertLessEqual(len(nodes), 2)


class ForecastRoleRollupTests(HierarchyFixture):
    """Team totals per role, from real forecast rows through the real data loader."""

    def setUp(self):
        super().setUp()
        fiscal_year, _ = FiscalYear.objects.get_or_create(company=self.company)
        self.instance = FiscalYearInstance.objects.create(
            fiscal_year_config=fiscal_year,
            start_date=date(2026, 1, 1),
            end_date=date(2026, 12, 31),
            name="FY 2026",
            is_current=True,
            company=self.company,
        )
        quarter = Quarter.objects.create(
            fiscal_year=self.instance,
            name="Q1",
            quarter_number=1,
            start_date=date(2026, 1, 1),
            end_date=date(2026, 3, 31),
            company=self.company,
        )
        self.period = Period.objects.create(
            quarter=quarter,
            name="Period 1",
            period_number=1,
            start_date=date(2026, 1, 1),
            end_date=date(2026, 1, 31),
            company=self.company,
        )
        self.forecast_type = ForecastType.objects.create(
            name="Revenue", company=self.company
        )
        for user, closed in (
            (self.head, 100),
            (self.manager, 200),
            (self.rep, 300),
            (self.rep2, 400),
            (self.peer, 1000),
        ):
            Forecast.objects.create(
                name=f"f-{user.username}",
                forecast_type=self.forecast_type,
                period=self.period,
                quarter=quarter,
                fiscal_year=self.instance,
                owner=user,
                company=self.company,
                closed_amount=closed,
                actual_amount=closed,
                commit_amount=closed / 2,
            )
        for user, target in ((self.manager, 1000), (self.rep, 500)):
            ForecastTarget.objects.create(
                assigned_to=user,
                period=self.period,
                forcasts_type=self.forecast_type,
                target_amount=target,
                company=self.company,
            )

    def role_rows(self, user, owner_ids):
        """Role rows for the period, as the forecast table loads them for ``user``."""

        class Loader(ForecastTypeTabMixin, ForecastTypeTabHelpersMixin):
            """The data-loading half of the forecast tab view."""

            USERS_PER_PAGE = 10

            def __init__(self, request):
                self.request = request

        request = SimpleNamespace(active_company=self.company, user=user)
        forecasts = Loader(request).get_forecast_data(
            self.forecast_type, self.instance, None, 1, owner_ids=owner_ids
        )
        return {row.role_name: row for row in forecasts[0].role_rows}, forecasts[
            0
        ].role_rows

    def test_admin_totals_add_up_through_the_hierarchy(self):
        """A role's row is its own users plus every role below it."""
        by_name, _ = self.role_rows(self.superuser, None)
        self.assertEqual(float(by_name["Head"].closed_amount), 1000)  # 100+200+300+400
        self.assertEqual(float(by_name["Manager"].closed_amount), 900)  # 200+300+400
        self.assertEqual(float(by_name["Rep"].closed_amount), 700)  # 300+400
        self.assertEqual(float(by_name["Other"].closed_amount), 1000)  # peer
        self.assertEqual(float(by_name["Head"].commit_amount), 500)

    def test_targets_roll_up_the_same_way(self):
        """Team target is the sum of the targets of everyone in the subtree."""
        by_name, _ = self.role_rows(self.superuser, None)
        self.assertEqual(float(by_name["Manager"].target_amount), 1500)  # 1000+500
        self.assertEqual(float(by_name["Rep"].target_amount), 500)
        self.assertEqual(float(by_name["Head"].target_amount), 1500)

    def test_rows_are_ordered_and_indented_by_depth(self):
        """Head, then Manager below it, then Rep below that."""
        _, rows = self.role_rows(self.superuser, None)
        depths = [
            (r.role_name, r.depth)
            for r in rows
            if r.role_name in ("Head", "Manager", "Rep")
        ]
        self.assertEqual(depths, [("Head", 0), ("Manager", 1), ("Rep", 2)])

    def test_manager_only_sees_their_own_team(self):
        """No boss, no peers: just the manager's role and the reps below."""
        scope = get_forecast_owner_scope(self.manager)
        by_name, rows = self.role_rows(self.manager, scope)
        self.assertEqual([r.role_name for r in rows], ["Manager", "Rep"])
        self.assertEqual(float(by_name["Manager"].closed_amount), 900)
        self.assertEqual(rows[0].depth, 0)
        self.assertNotIn("Head", by_name)
        self.assertNotIn("Other", by_name)

    def test_a_single_role_gets_no_role_rows(self):
        """A rep with no team would see one redundant row, so none are built."""
        _, rows = self.role_rows(self.rep, get_forecast_owner_scope(self.rep))
        self.assertEqual(rows, [])

    def test_role_row_template_shows_totals_depth_and_toggle(self):
        """The rendered row has the team total, indentation and a toggle only when needed."""
        from django.template.loader import render_to_string

        by_name, _ = self.role_rows(self.superuser, None)
        period_row = SimpleNamespace(
            view_id=f"period_{self.period.pk}", period=self.period
        )

        def render(name):
            return render_to_string(
                "forecast_role_row.html",
                {
                    "role_row": by_name[name],
                    "forecast": period_row,
                    "forecast_type": self.forecast_type,
                    "fiscal_year": self.instance,
                    "currency_symbol": "USD",
                },
            )

        manager = render("Manager")
        self.assertIn("Manager", manager)
        self.assertIn("900", manager)
        self.assertIn('class="role-toggle', manager)
        self.assertIn(f'data-parent="period_{self.period.pk}-', manager)
        self.assertIn("calc(0.75rem + 1 * 1rem)", manager)
        rep = render("Rep")
        self.assertNotIn('class="role-toggle', rep)
        self.assertIn("calc(0.75rem + 2 * 1rem)", rep)
        self.assertNotIn("data-parent", render("Head"))
        # roles with users of their own get the "N users" control that loads them
        self.assertIn("role-users-toggle", rep)
        self.assertIn(f"role_id={self.rep.role_id}", rep)
        self.assertIn(f"period_id={self.period.pk}", rep)
        self.assertIn("2 users", rep)
        self.assertIn("3 in team", manager)
        # arrows behave like the period row's: right when closed, turned down when open
        self.assertIn('style="transform: rotate(90deg)"', manager)  # role arrow: open
        self.assertIn("M10 9a3 3 0 100-6", rep)  # the users control shows a person icon
        self.assertEqual(rep.count("rotate("), 0)  # and has no expand arrow of its own
        self.assertNotIn("rotate-90", manager)

    def role_users(self, user, role_id, **extra):
        """Open a role's users the way the "N users" control does."""
        from django.urls import reverse

        self.client.force_login(user)
        params = {
            "forecast_type_id": self.forecast_type.pk,
            "fiscal_year_id": self.instance.pk,
            "period_id": self.period.pk,
            "role_id": role_id,
            "depth": 1,
        }
        params.update(extra)
        response = self.client.get(
            reverse("forecast:forecast_role_users"), params, HTTP_HX_REQUEST="true"
        )
        self.assertEqual(response.status_code, 200)
        return response.content.decode()

    def test_role_users_lists_the_users_of_that_role(self):
        """A view-all user opening the Rep role gets exactly its two users, keyed to the role."""
        html = self.role_users(self.viewer, self.rep.role_id)
        self.assertIn(">rep<", html)
        self.assertIn(">rep2<", html)
        self.assertNotIn(">manager<", html)
        # each user shows their profile picture (or generated avatar), not a stock icon
        self.assertEqual(html.count("ui-avatars.com") + html.count("/media/"), 2)
        self.assertNotIn("M10 9a3 3 0 100-6", html)
        key = f"period_{self.period.pk}-{self.rep.role_id}"
        self.assertEqual(html.count(f'data-users-of="{key}"'), 2)
        # icon lines up under the role name (depth 1 here: its indent plus arrow and gap)
        self.assertIn("padding-inline-start: calc(0.75rem + 1 * 1rem + 1.75rem)", html)

    def test_role_users_respects_the_hierarchy(self):
        """A manager cannot read users outside their team by asking for another role."""
        for role_id in (self.head.role_id, self.peer.role_id):
            html = self.role_users(self.manager, role_id)
            self.assertIn("No users to show for this role.", html)
            self.assertNotIn(">head<", html)
            self.assertNotIn(">peer<", html)
        # their own team is fine
        self.assertIn(">rep2<", self.role_users(self.manager, self.rep.role_id))

    def test_role_users_for_a_user_without_a_team_is_only_themselves(self):
        """A rep asking for their own role gets themselves, not their colleague."""
        html = self.role_users(self.rep, self.rep.role_id)
        self.assertIn(">rep<", html)
        self.assertNotIn(">rep2<", html)

    def test_role_users_pages_ten_at_a_time(self):
        """More than a page of users shows the loading row and a next-page link."""
        for index in range(12):
            self.make_user(f"extra{index}", self.rep.role)
        first = self.role_users(self.viewer, self.rep.role_id)
        key = f"period_{self.period.pk}-{self.rep.role_id}"
        self.assertEqual(first.count("htmx-sentinel"), 1)
        self.assertIn(f'id="role-hint-{key}"', first)
        self.assertIn("page=2", first)
        # the previous spinner plus a button, so loading never depends on scrolling alone
        self.assertIn(f'id="role-loading-{key}"', first)
        self.assertIn("Loading More Users", first)
        self.assertIn(f'data-role-key="{key}"', first)
        self.assertIn("Load More Users", first)
        # 14 users in all: page 2 holds the last 4, so nothing more to load
        last = self.role_users(self.viewer, self.rep.role_id, page=2)
        self.assertEqual(last.count("htmx-sentinel"), 0)
        self.assertNotIn(f'id="role-hint-{key}"', last)
        self.assertNotIn("Load More Users", last)
        self.assertEqual(last.count(f'data-users-of="{key}"'), 4)

    def test_tab_page_nests_users_under_roles_instead_of_a_flat_list(self):
        """With role rows, users load under their role; the flat user list is not rendered."""
        from django.urls import reverse

        self.client.force_login(self.viewer)
        response = self.client.get(
            reverse(
                "forecast:forecast_type_tab_view", kwargs={"pk": self.forecast_type.pk}
            ),
            {"fiscal_year_id": self.instance.pk},
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(response.status_code, 200)
        html = response.content.decode()
        self.assertIn("role-subtotal-row", html)
        self.assertIn("/crm/forecast/forecast-role-users/?", html)
        self.assertIn("role-users-toggle", html)
        self.assertNotIn('class="user-details-row', html)
        self.assertIn("function toggleRoleUsers", html)

    def stamp_manager_role_total(self, total="1500"):
        """Mark the manager and rep targets (1000 + 500) as one Manager role total."""
        for target in ForecastTarget.objects.filter(period=self.period):
            target.additional_info = role_targets.stamp(
                None,
                batch="batch-1",
                role=self.manager.role,
                total=Decimal(total),
                include_below=True,
                share=target.target_amount,
                user=self.superuser,
            )
            target.save()

    def test_role_rows_flag_a_role_total_that_no_longer_adds_up(self):
        """Change one user's target and the role's row shows the difference."""
        self.stamp_manager_role_total("1500")
        by_name, _rows = self.role_rows(self.superuser, None)
        self.assertTrue(by_name["Manager"].role_target["matches"])
        self.assertEqual(by_name["Manager"].role_target["total"], Decimal("1500"))

        rep_target = ForecastTarget.objects.get(assigned_to=self.rep)
        rep_target.target_amount = Decimal("600")
        rep_target.save()
        by_name, _rows = self.role_rows(self.superuser, None)
        note = by_name["Manager"].role_target
        self.assertFalse(note["matches"])
        self.assertEqual(note["current"], Decimal("1600"))
        self.assertEqual(note["difference"], Decimal("-100"))

    def test_roles_without_a_role_total_note_are_never_flagged(self):
        """Targets saved before this existed carry no note, so no row has one."""
        by_name, _rows = self.role_rows(self.superuser, None)
        self.assertTrue(all(row.role_target is None for row in by_name.values()))

    def test_role_row_template_shows_the_role_total_and_the_difference(self):
        """Matching: a quiet 'Role target' line. Drifted: a red 'now' figure."""
        from django.template.loader import render_to_string

        def render():
            by_name, _rows = self.role_rows(self.superuser, None)
            return render_to_string(
                "forecast_role_row.html",
                {
                    "role_row": by_name["Manager"],
                    "forecast": SimpleNamespace(
                        view_id=f"period_{self.period.pk}", period=self.period
                    ),
                    "forecast_type": self.forecast_type,
                    "fiscal_year": self.instance,
                    "currency_symbol": "USD",
                },
            )

        self.stamp_manager_role_total("1500")
        ok = render()
        self.assertIn("Role target 1,500", ok)
        self.assertNotIn("now 1,600", ok)
        rep_target = ForecastTarget.objects.get(assigned_to=self.rep)
        rep_target.target_amount = Decimal("600")
        rep_target.save()
        drifted = render()
        self.assertIn("Role target 1,500", drifted)
        self.assertIn("now 1,600", drifted)


class IncludeRolesBelowTests(HierarchyFixture):
    """One total divided by role across a role and every role below it."""

    def setUp(self):
        super().setUp()
        fiscal_year, _created = FiscalYear.objects.get_or_create(company=self.company)
        instance = FiscalYearInstance.objects.create(
            fiscal_year_config=fiscal_year,
            start_date=date(2026, 1, 1),
            end_date=date(2026, 12, 31),
            name="FY 2026",
            company=self.company,
        )
        quarter = Quarter.objects.create(
            fiscal_year=instance,
            name="Q1",
            quarter_number=1,
            start_date=date(2026, 1, 1),
            end_date=date(2026, 3, 31),
            company=self.company,
        )
        self.period = Period.objects.create(
            quarter=quarter,
            name="Period 1",
            period_number=1,
            start_date=date(2026, 1, 1),
            end_date=date(2026, 1, 31),
            company=self.company,
        )
        self.forecast_type = ForecastType.objects.create(
            name="Revenue", company=self.company
        )

    def post_data(self, role_id, shares=None, user_shares=None, **overrides):
        """POST data for a total of 100 over ``role_id`` and the roles below it."""
        data = {
            "is_role_based": "on",
            "is_whole_role": "on",
            "include_below": "on",
            "role": str(role_id),
            "wr_amount": "100",
            "wr_period": str(self.period.pk),
            "wr_type": str(self.forecast_type.pk),
        }
        for share_role_id, value in (shares or {}).items():
            data[f"share_role_{share_role_id}"] = value
        for user, value in (user_shares or {}).items():
            data[f"share_user_{user.pk}"] = value
        if shares or user_shares:
            data["wr_manual"] = "1"
        data.update(overrides)
        return data

    def request_as(self, user, data):
        """POST request authenticated as ``user``."""
        request = RequestFactory().post("/", data)
        request.user = user
        return request

    def context(self, user, data):
        """The split context the form builds for ``data``."""
        return build_whole_role_context(self.request_as(user, data), data)

    def rows(self, context):
        """(role name, depth, users, share) for each role row."""
        return [
            (r["name"], r["depth"], r["user_count"], r["share"])
            for r in context["wr_role_rows"]
        ]

    def save_as(self, user, data):
        """Run the whole-role save as ``user``; return (response, form errors)."""
        view = ForecastTargetFormView()
        request = self.request_as(user, data)
        request.session = {}
        request._messages = mock.MagicMock()
        view.request = request
        view.kwargs = {}
        form = mock.MagicMock()
        errors = []
        form.add_error.side_effect = lambda field, message: errors.append(str(message))
        with mock.patch.object(
            ForecastTargetFormView, "form_invalid", return_value="invalid"
        ):
            response = view.save_whole_role(form)
        return response, errors

    def saved(self):
        """{username: amount} of the targets created for the period."""
        return {
            t.assigned_to.username: t.target_amount
            for t in ForecastTarget.objects.filter(period=self.period)
        }

    def test_shares_start_equal_per_user_down_the_hierarchy(self):
        """Head, Manager and Rep: four users, so 25 each and Rep (two users) gets 50."""
        context = self.context(self.superuser, self.post_data(self.head.role_id))
        self.assertEqual(
            self.rows(context),
            [
                ("Head", 0, 1, Decimal("25")),
                ("Manager", 1, 1, Decimal("25")),
                ("Rep", 2, 2, Decimal("50")),
            ],
        )
        self.assertEqual(context["wr_remaining"], 0)
        self.assertEqual(context["wr_mode"], "roles")

    def test_save_divides_each_roles_share_among_its_users(self):
        """Equal split: one target per user, tagged with the user's own role."""
        response, errors = self.save_as(
            self.superuser, self.post_data(self.head.role_id)
        )
        self.assertEqual(errors, [])
        self.assertNotEqual(response, "invalid")
        self.assertEqual(
            self.saved(),
            {
                "head": Decimal("25"),
                "manager": Decimal("25"),
                "rep": Decimal("25"),
                "rep2": Decimal("25"),
            },
        )
        roles = {
            t.assigned_to.username: t.role_id
            for t in ForecastTarget.objects.filter(period=self.period)
        }
        self.assertEqual(roles["rep"], self.rep.role_id)
        self.assertEqual(roles["head"], self.head.role_id)

    def test_uneven_role_shares_are_kept(self):
        """Head 10, Manager 20, Rep 70: the two reps get 35 each."""
        data = self.post_data(
            self.head.role_id,
            shares={
                self.head.role_id: "10",
                self.manager.role_id: "20",
                self.rep.role_id: "70",
            },
        )
        self.save_as(self.superuser, data)
        self.assertEqual(
            self.saved(),
            {
                "head": Decimal("10"),
                "manager": Decimal("20"),
                "rep": Decimal("35"),
                "rep2": Decimal("35"),
            },
        )

    def test_the_saved_targets_always_add_up_to_the_total(self):
        """100 over three users: the cent that cannot be split goes to the last one."""
        self.save_as(self.superuser, self.post_data(self.manager.role_id))
        saved = self.saved()
        self.assertEqual(sum(saved.values()), Decimal("100.00"))
        self.assertEqual(saved["manager"], Decimal("33.33"))
        self.assertEqual(
            {saved["rep"], saved["rep2"]}, {Decimal("33.33"), Decimal("33.34")}
        )

    def test_shares_that_do_not_add_up_are_refused(self):
        """Nothing is created when the role shares miss the total."""
        data = self.post_data(
            self.head.role_id,
            shares={
                self.head.role_id: "10",
                self.manager.role_id: "20",
                self.rep.role_id: "60",
            },
        )
        response, errors = self.save_as(self.superuser, data)
        self.assertEqual(response, "invalid")
        self.assertIn("Shares must add up to the role target.", errors)
        self.assertFalse(ForecastTarget.objects.exists())

    def test_an_existing_target_blocks_the_whole_save(self):
        """One user already having a target means no target is created at all."""
        ForecastTarget.objects.create(
            assigned_to=self.rep,
            period=self.period,
            forcasts_type=self.forecast_type,
            target_amount=1,
            company=self.company,
        )
        response, errors = self.save_as(
            self.superuser, self.post_data(self.head.role_id)
        )
        self.assertEqual(response, "invalid")
        self.assertTrue(any("already exists" in e for e in errors))
        self.assertEqual(ForecastTarget.objects.count(), 1)

    def test_a_manager_cannot_reach_roles_above_their_own(self):
        """Choosing the Head role is refused, and nothing is created."""
        response, errors = self.save_as(self.manager, self.post_data(self.head.role_id))
        self.assertEqual(response, "invalid")
        self.assertIn("Select a role you can set targets for.", errors)
        self.assertFalse(ForecastTarget.objects.exists())

    def test_a_manager_splits_only_among_users_below_them(self):
        """The Rep role is theirs to split; the manager is never included."""
        data = self.post_data(self.rep.role_id)
        context = self.context(self.manager, data)
        self.assertEqual(self.rows(context), [("Rep", 0, 2, Decimal("100"))])
        response, errors = self.save_as(self.manager, data)
        self.assertEqual(errors, [])
        self.assertEqual(self.saved(), {"rep": Decimal("50"), "rep2": Decimal("50")})

    def test_empty_roles_are_skipped_without_leaving_a_depth_gap(self):
        """Head > Empty (no users) > Deep: Deep shows one level in, not two."""
        empty = Role.objects.create(
            role_name="Empty", parent_role=self.head.role, company=self.company
        )
        deep = Role.objects.create(
            role_name="Deep", parent_role=empty, company=self.company
        )
        self.make_user("deepuser", deep)
        nodes = role_split_nodes(self.request_as(self.superuser, {}), self.head.role_id)
        self.assertEqual(
            [(n["name"], n["depth"]) for n in nodes],
            # siblings are alphabetical (Empty, then Manager); Deep sits one level in
            [("Head", 0), ("Deep", 1), ("Manager", 1), ("Rep", 2)],
        )

    def test_form_shows_a_role_table_only_when_roles_below_are_included(self):
        """The same toggle request renders role rows with the switch, user rows without."""
        from django.urls import reverse

        self.client.force_login(self.viewer)
        self.viewer.user_permissions.add(
            Permission.objects.get(
                content_type__app_label="forecast", codename="change_forecasttarget"
            )
        )
        url = reverse("forecast:toggle_role_based")
        base = {
            "is_role_based": "on",
            "is_whole_role": "on",
            "role": str(self.head.role_id),
            "wr_amount": "100",
        }
        below = self.client.post(
            url, dict(base, include_below="on"), HTTP_HX_REQUEST="true"
        ).content.decode()
        self.assertIn(f'name="share_role_{self.head.role_id}"', below)
        self.assertIn("Split By Role", below)
        self.assertIn("Include Roles Below", below)
        plain = self.client.post(url, base, HTTP_HX_REQUEST="true").content.decode()
        self.assertIn(f'name="share_{self.head.pk}"', plain)
        self.assertNotIn("share_role_", plain)
        self.assertIn("Include Roles Below", plain)  # the switch is offered either way

    def test_individual_user_shares_are_saved_as_entered(self):
        """Different amounts per user: the two reps need not get the same."""
        data = self.post_data(
            self.head.role_id,
            user_shares={
                self.head: "5",
                self.manager: "5",
                self.rep: "60",
                self.rep2: "30",
            },
        )
        response, errors = self.save_as(self.superuser, data)
        self.assertEqual(errors, [])
        self.assertEqual(
            self.saved(),
            {
                "head": Decimal("5"),
                "manager": Decimal("5"),
                "rep": Decimal("60"),
                "rep2": Decimal("30"),
            },
        )

    def test_a_roles_total_is_the_sum_of_its_users_shares(self):
        """Editing users changes the role's total, which the table shows."""
        data = self.post_data(
            self.head.role_id,
            user_shares={
                self.head: "5",
                self.manager: "5",
                self.rep: "60",
                self.rep2: "30",
            },
        )
        context = self.context(self.superuser, data)
        self.assertEqual(
            [(r["name"], r["share"]) for r in context["wr_role_rows"]],
            [("Head", Decimal("5")), ("Manager", Decimal("5")), ("Rep", Decimal("90"))],
        )
        self.assertEqual(context["wr_remaining"], 0)

    def test_user_shares_that_do_not_add_up_are_refused(self):
        """90 of 100 handed out: refused, nothing is created."""
        data = self.post_data(
            self.head.role_id,
            user_shares={
                self.head: "5",
                self.manager: "5",
                self.rep: "50",
                self.rep2: "30",
            },
        )
        response, errors = self.save_as(self.superuser, data)
        self.assertEqual(response, "invalid")
        self.assertIn("Shares must add up to the role target.", errors)
        self.assertFalse(ForecastTarget.objects.exists())

    def test_user_figures_win_over_role_figures_when_both_are_posted(self):
        """The browser posts both; the users' own amounts are what get saved."""
        data = self.post_data(
            self.head.role_id,
            shares={
                self.head.role_id: "25",
                self.manager.role_id: "25",
                self.rep.role_id: "50",
            },
            user_shares={
                self.head: "25",
                self.manager: "25",
                self.rep: "40",
                self.rep2: "10",
            },
        )
        self.save_as(self.superuser, data)
        saved = self.saved()
        self.assertEqual((saved["rep"], saved["rep2"]), (Decimal("40"), Decimal("10")))

    def test_table_has_a_user_row_with_its_own_input_under_each_role(self):
        """Every user gets an input, hidden until the role is expanded."""
        from django.urls import reverse

        self.client.force_login(self.viewer)
        self.viewer.user_permissions.add(
            Permission.objects.get(
                content_type__app_label="forecast", codename="change_forecasttarget"
            )
        )
        html = self.client.post(
            reverse("forecast:toggle_role_based"),
            {
                "is_role_based": "on",
                "is_whole_role": "on",
                "include_below": "on",
                "role": str(self.head.role_id),
                "wr_amount": "100",
            },
            HTTP_HX_REQUEST="true",
        ).content.decode()
        role_rows = 'class="border-t border-dark-50 bg-primary-100 wr-role-row"'
        user_rows = 'class="hidden border-t border-dark-50 wr-user-row"'
        self.assertEqual(html.count(role_rows), 3)  # Head, Manager, Rep
        self.assertEqual(html.count(user_rows), 4)  # one per user, hidden by default
        self.assertEqual(html.count('name="share_user_'), 4)
        self.assertEqual(html.count('class="wr-expand'), 3)
        self.assertIn("ui-avatars.com", html)

    # ----- the role total that was entered is remembered, and checked on every change

    def no_request_cache(self):
        """The per-request cache of batch sums would hide a change made in the same test."""
        return mock.patch.object(
            role_targets, "_thread_local", SimpleNamespace(request=None)
        )

    def test_every_target_of_a_split_carries_the_same_role_total_note(self):
        """One batch id, the role, the total entered, and each user's own share."""
        self.save_as(self.superuser, self.post_data(self.head.role_id))
        notes = [
            (t.assigned_to.username, t.target_amount, role_targets.note_of(t))
            for t in ForecastTarget.objects.filter(period=self.period)
        ]
        self.assertEqual(len(notes), 4)
        self.assertEqual(len({n["batch"] for _u, _a, n in notes}), 1)
        for _username, amount, note in notes:
            self.assertEqual(note["role_id"], self.head.role_id)
            self.assertEqual(note["role_name"], "Head")
            self.assertEqual(note["total"], "100")
            self.assertTrue(note["include_below"])
            self.assertEqual(Decimal(note["share"]), amount)
            self.assertEqual(note["set_by"], self.superuser.pk)

    def test_a_plain_split_is_noted_too_without_include_below(self):
        """Splitting one role's users also remembers the total."""
        data = self.post_data(self.rep.role_id)
        data.pop("include_below")
        self.save_as(self.superuser, data)
        note = role_targets.note_of(ForecastTarget.objects.get(assigned_to=self.rep))
        self.assertEqual((note["role_name"], note["total"]), ("Rep", "100"))
        self.assertFalse(note["include_below"])

    def test_the_note_is_merged_not_overwritten(self):
        """Another feature's keys in additional_info survive being stamped."""
        info = role_targets.stamp(
            {"approval_cycle_started_at": "x"},
            batch="b",
            role=self.head.role,
            total=Decimal("10"),
            include_below=False,
            share=Decimal("10"),
            user=self.superuser,
        )
        self.assertEqual(info["approval_cycle_started_at"], "x")
        self.assertIn("role_target", info)

    def test_a_change_to_one_target_shows_in_the_comparison(self):
        """Edit one user's target: the role total no longer matches, by exactly that much."""
        self.save_as(self.superuser, self.post_data(self.head.role_id))
        rep = ForecastTarget.objects.get(assigned_to=self.rep)
        with self.no_request_cache():
            before = role_targets.status_of(rep)
            self.assertTrue(before["matches"])
            self.assertEqual(
                (before["total"], before["current"], before["members"]),
                (Decimal("100"), Decimal("100"), 4),
            )
            rep.target_amount += Decimal("7")
            rep.save()
            after = role_targets.status_of(ForecastTarget.objects.get(pk=rep.pk))
        self.assertFalse(after["matches"])
        self.assertEqual(after["current"], Decimal("107"))
        self.assertEqual(after["difference"], Decimal("-7"))

    def test_deleting_a_target_also_shows_in_the_comparison(self):
        """Removing one user's target leaves the role short."""
        self.save_as(self.superuser, self.post_data(self.head.role_id))
        ForecastTarget.objects.get(assigned_to=self.rep2).delete()
        with self.no_request_cache():
            status = role_targets.status_of(
                ForecastTarget.objects.get(assigned_to=self.rep)
            )
        self.assertEqual(
            (status["current"], status["difference"], status["members"]),
            (Decimal("75"), Decimal("25"), 3),
        )

    def test_a_target_saved_before_this_existed_has_no_note_and_no_status(self):
        """Old targets are untouched and never flagged."""
        old = ForecastTarget.objects.create(
            assigned_to=self.rep,
            period=self.period,
            forcasts_type=self.forecast_type,
            target_amount=50,
            company=self.company,
        )
        self.assertIsNone(role_targets.note_of(old))
        self.assertIsNone(role_targets.status_of(old))
        self.assertIn("-", old.role_target_col())
        self.assertNotIn("Now adds up", old.role_target_col())

    def test_list_column_names_the_role_total_and_flags_drift(self):
        """'Head · 100' while it adds up; 'Now adds up to 107' once it does not."""
        self.save_as(self.superuser, self.post_data(self.head.role_id))
        rep = ForecastTarget.objects.get(assigned_to=self.rep)
        with self.no_request_cache():
            ok = rep.role_target_col()
            self.assertIn("Head", ok)
            self.assertIn("100", ok)
            self.assertNotIn("Now adds up", ok)
            rep.target_amount += Decimal("7")
            rep.save()
            drifted = ForecastTarget.objects.get(pk=rep.pk).role_target_col()
        self.assertIn("Now adds up to 107", drifted)

    def open_edit_form(self, target):
        """Open the edit form of ``target`` the way the list's Edit icon does."""
        from django.urls import reverse

        self.viewer.user_permissions.add(
            Permission.objects.get(
                content_type__app_label="forecast", codename="change_forecasttarget"
            )
        )
        self.client.force_login(self.viewer)
        return self.client.get(
            reverse(
                "forecast:forecast_target_update_form_view", kwargs={"pk": target.pk}
            ),
            HTTP_HX_REQUEST="true",
        )

    def test_edit_form_compares_the_role_total_before_you_save(self):
        """The note names the role total and what the other targets add up to."""
        self.save_as(self.viewer, self.post_data(self.head.role_id))
        rep = ForecastTarget.objects.get(assigned_to=self.rep)
        response = self.open_edit_form(rep)
        self.assertEqual(response.status_code, 200)
        html = response.content.decode()
        self.assertIn('id="role-target-note"', html)
        self.assertIn("Part of the Head role target of <b>100</b>", html)
        self.assertIn(
            "The other targets add up to <b>75</b>", html
        )  # 100 minus this 25
        self.assertIn('data-others="75', html)

    def test_edit_form_of_an_ordinary_target_has_no_comparison(self):
        """No role total, no note."""
        old = ForecastTarget.objects.create(
            assigned_to=self.rep,
            period=self.period,
            forcasts_type=self.forecast_type,
            target_amount=50,
            company=self.company,
        )
        html = self.open_edit_form(old).content.decode()
        self.assertNotIn("role-target-note", html)

    def test_saving_an_edit_warns_when_the_role_total_no_longer_adds_up(self):
        """Change a user's target: a warning names the role and the new total."""
        from django.contrib.messages import get_messages
        from django.urls import reverse

        self.save_as(self.viewer, self.post_data(self.head.role_id))
        rep = ForecastTarget.objects.get(assigned_to=self.rep)
        self.open_edit_form(rep)  # logs in as the view-all user with change rights
        response = self.client.post(
            reverse("forecast:forecast_target_update_form_view", kwargs={"pk": rep.pk}),
            {"target_amount": "32"},
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(response.status_code, 200)
        rep.refresh_from_db()
        self.assertEqual(rep.target_amount, Decimal("32.00"))
        warnings = [
            str(m)
            for m in get_messages(response.wsgi_request)
            if m.level_tag == "warning"
        ]
        self.assertEqual(len(warnings), 1)
        self.assertIn("Head role target of 100", warnings[0])
        self.assertIn("now add up to 107", warnings[0])

    def test_an_edit_that_keeps_the_total_gives_no_warning(self):
        """Move 5 from one user to another: still adds up, so nothing to warn about."""
        from django.contrib.messages import get_messages
        from django.urls import reverse

        self.save_as(self.viewer, self.post_data(self.head.role_id))
        rep, rep2 = (
            ForecastTarget.objects.get(assigned_to=u) for u in (self.rep, self.rep2)
        )
        rep2.target_amount -= Decimal("5")
        rep2.save()
        self.open_edit_form(rep)
        response = self.client.post(
            reverse("forecast:forecast_target_update_form_view", kwargs={"pk": rep.pk}),
            {"target_amount": "30"},
            HTTP_HX_REQUEST="true",
        )
        self.assertEqual(response.status_code, 200)
        warnings = [
            m for m in get_messages(response.wsgi_request) if m.level_tag == "warning"
        ]
        self.assertEqual(warnings, [])

    def test_an_existing_users_saved_column_layout_still_shows_role_target(self):
        """A layout saved before the column existed must not hide it."""
        from django.urls import reverse

        from horilla.contrib.core.models import ListColumnVisibility

        # split targets are listed as role totals now, so give the list a one-off target
        self.one_off_target(self.peer)
        self.split_as_viewer()
        self.viewer.user_permissions.add(
            Permission.objects.get(
                content_type__app_label="forecast", codename="view_forecasttarget"
            )
        )
        self.client.force_login(self.viewer)
        url = reverse("forecast:forecast_target_list_view")
        params = {"forecast_type": self.forecast_type.pk, "period": self.period.pk}

        from django.core.cache import cache

        cache.clear()  # an earlier test may have cached this user's columns
        found = dict(params, search="rep")
        first = self.client.get(url, found, HTTP_HX_REQUEST="true").content.decode()
        self.assertIn("Role Target", first)  # a search lists split users, so it shows
        plain = self.client.get(url, params, HTTP_HX_REQUEST="true").content.decode()
        self.assertNotIn(
            "Role Target", plain.split('id="forecast-target-list"')[1]
        )  # individual targets have no role total

        # what an existing user has stored: the three original columns only
        saved = ListColumnVisibility.all_objects.filter(
            user=self.viewer, model_name="ForecastTarget"
        )
        self.assertTrue(saved.exists())
        saved.update(
            visible_fields=[
                ["Assigned User", "assigned_to"],
                ["Role", "assigned_to__role"],
                ["Target", "target_amount"],
            ]
        )
        cache.clear()
        again = self.client.get(url, found, HTTP_HX_REQUEST="true").content.decode()
        self.assertIn("Role Target", again)
        # and the saved layout itself was not rewritten
        self.assertEqual(saved.first().visible_fields[-1], ["Target", "target_amount"])

    # ----- Option A: change the role total on purpose, and a warning when deleting

    def split_as_viewer(self):
        """A role total of 100 over Head, Manager and the two reps (25 each)."""
        self.save_as(self.viewer, self.post_data(self.head.role_id))
        return {
            t.assigned_to.username: t
            for t in ForecastTarget.objects.filter(period=self.period)
        }

    def grant(self, user, *codenames):
        """Give ``user`` forecast permissions."""
        for codename in codenames:
            user.user_permissions.add(
                Permission.objects.get(
                    content_type__app_label="forecast", codename=codename
                )
            )

    def edit(self, target, amount, switch=False):
        """Save a new amount for ``target`` the way the edit form does."""
        from django.urls import reverse

        data = {"target_amount": str(amount)}
        if switch:
            data["update_role_total"] = "on"
        return self.client.post(
            reverse(
                "forecast:forecast_target_update_form_view", kwargs={"pk": target.pk}
            ),
            data,
            HTTP_HX_REQUEST="true",
        )

    def message_texts(self, response, level):
        """Messages of one level ('warning', 'success') queued by ``response``."""
        from django.contrib.messages import get_messages

        return [
            str(m) for m in get_messages(response.wsgi_request) if m.level_tag == level
        ]

    def test_money_is_written_the_way_people_read_it(self):
        """Thousands separators, and no needless decimals."""
        self.assertEqual(role_targets.money("1030.50"), "1,030.5")
        self.assertEqual(role_targets.money(1000), "1,000")
        self.assertEqual(role_targets.money(Decimal("75")), "75")

    def test_changing_the_total_updates_every_target_of_the_batch(self):
        """All four notes get the new total; each remembers the old one and who changed it."""
        targets = self.split_as_viewer()
        for target in targets.values():
            target.additional_info = {**target.additional_info, "other_feature": 1}
            target.save()
        changed = role_targets.change_total(
            ForecastTarget,
            role_targets.note_of(targets["rep"])["batch"],
            Decimal("107"),
            self.viewer,
        )
        self.assertEqual(changed, 4)
        for target in ForecastTarget.objects.filter(period=self.period):
            note = role_targets.note_of(target)
            self.assertEqual(note["total"], "107")
            self.assertEqual(note["previous_total"], "100")
            self.assertEqual(note["total_changed_by"], self.viewer.pk)
            self.assertEqual(
                target.additional_info["other_feature"], 1
            )  # merged, not replaced

    def test_only_someone_who_can_set_every_target_may_change_a_total(self):
        """A manager cannot move a total that also covers the boss's own target."""
        targets = self.split_as_viewer()
        batch = role_targets.note_of(targets["rep"])["batch"]
        self.assertTrue(
            role_targets.can_change_total(self.viewer, ForecastTarget, batch)
        )
        self.assertFalse(
            role_targets.can_change_total(self.manager, ForecastTarget, batch)
        )
        # a total that covers only the manager's own reports is theirs to change
        ForecastTarget.objects.all().delete()
        data = self.post_data(self.rep.role_id)
        self.save_as(self.viewer, data)
        reps = ForecastTarget.objects.get(assigned_to=self.rep)
        self.assertTrue(
            role_targets.can_change_total(
                self.manager, ForecastTarget, role_targets.note_of(reps)["batch"]
            )
        )

    def test_edit_form_offers_the_switch_only_where_it_applies(self):
        """Offered for a target in a role total; not for an ordinary one."""
        targets = self.split_as_viewer()
        self.grant(self.viewer, "change_forecasttarget")
        self.client.force_login(self.viewer)
        from django.urls import reverse

        def form(target):
            return self.client.get(
                reverse(
                    "forecast:forecast_target_update_form_view",
                    kwargs={"pk": target.pk},
                ),
                HTTP_HX_REQUEST="true",
            ).content.decode()

        html = form(targets["rep"])
        self.assertIn('id="id_update_role_total"', html)
        self.assertIn("Also Change the Role Total", html)
        old = ForecastTarget.objects.create(
            assigned_to=self.peer,
            period=self.period,
            forcasts_type=self.forecast_type,
            target_amount=5,
            company=self.company,
        )
        self.assertNotIn('id="id_update_role_total"', form(old))

    def test_edit_form_hides_the_switch_from_a_manager_below_the_total(self):
        """The total covers the boss too, so the manager only sees the comparison."""
        targets = self.split_as_viewer()
        self.grant(self.manager, "change_forecasttarget")
        self.client.force_login(self.manager)
        from django.urls import reverse

        html = self.client.get(
            reverse(
                "forecast:forecast_target_update_form_view",
                kwargs={"pk": targets["rep"].pk},
            ),
            HTTP_HX_REQUEST="true",
        ).content.decode()
        self.assertIn("role-target-note", html)
        self.assertNotIn('id="id_update_role_total"', html)

    def test_edit_with_the_switch_on_makes_the_new_sum_the_role_total(self):
        """Raise one target by 7 and choose to move the total: it now matches, no warning."""
        targets = self.split_as_viewer()
        self.grant(self.viewer, "change_forecasttarget")
        self.client.force_login(self.viewer)
        response = self.edit(targets["rep"], 32, switch=True)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.message_texts(response, "warning"), [])
        success = self.message_texts(
            response, "success"
        )  # the form's own "saved" is another
        self.assertTrue(
            any("Head role target is now 107" in text for text in success), success
        )
        with self.no_request_cache():
            for target in ForecastTarget.objects.filter(period=self.period):
                status = role_targets.status_of(target)
                self.assertEqual(status["total"], Decimal("107"))
                self.assertTrue(status["matches"])

    def test_edit_with_the_switch_off_keeps_the_total_and_warns(self):
        """The default: the role total stays 100 and the difference is reported."""
        targets = self.split_as_viewer()
        self.grant(self.viewer, "change_forecasttarget")
        self.client.force_login(self.viewer)
        response = self.edit(targets["rep"], 32)
        warnings = self.message_texts(response, "warning")
        self.assertEqual(len(warnings), 1)
        self.assertIn("now add up to 107", warnings[0])
        with self.no_request_cache():
            status = role_targets.status_of(
                ForecastTarget.objects.get(pk=targets["rep"].pk)
            )
        self.assertEqual(
            (status["total"], status["current"]), (Decimal("100"), Decimal("107"))
        )

    def open_delete_modal(self, target, **params):
        """The modal the delete icon opens (the first step, or a later one via ``params``)."""
        from django.urls import reverse

        self.grant(self.viewer, "delete_forecasttarget")
        self.client.force_login(self.viewer)
        url = reverse("forecast:forecast_target_delete_view", kwargs={"pk": target.pk})
        if params:
            return self.client.post(url, params, HTTP_HX_REQUEST="true")
        return self.client.get(url, HTTP_HX_REQUEST="true")

    def test_delete_modal_says_what_the_role_will_add_up_to(self):
        """Both steps of the delete flow carry the note for a target in a role total."""
        targets = self.split_as_viewer()
        first = self.open_delete_modal(targets["rep"]).content.decode()
        self.assertIn("Select Delete Mode", first)
        self.assertIn("part of the Head role target of 100", first)
        self.assertIn("will add up to 75", first)
        confirm = self.open_delete_modal(
            targets["rep"],
            action="check_dependencies_with_mode",
            delete_mode="main_hard",
            record_id=targets["rep"].pk,
        ).content.decode()
        self.assertIn("Confirm Delete", confirm)
        self.assertIn("will add up to 75", confirm)

    def test_delete_modal_of_an_ordinary_target_has_no_note(self):
        """Nothing extra for a target that is not part of a role total."""
        old = ForecastTarget.objects.create(
            assigned_to=self.peer,
            period=self.period,
            forcasts_type=self.forecast_type,
            target_amount=5,
            company=self.company,
        )
        html = self.open_delete_modal(old).content.decode()
        self.assertIn("Select Delete Mode", html)
        self.assertNotIn("role target of", html)

    def test_deleting_a_target_warns_that_the_role_no_longer_adds_up(self):
        """After the delete, a warning gives the role total and what is left."""
        targets = self.split_as_viewer()
        response = self.open_delete_modal(
            targets["rep"], delete_mode="main_hard", check_dependencies="false"
        )
        self.assertFalse(ForecastTarget.objects.filter(pk=targets["rep"].pk).exists())
        warnings = self.message_texts(response, "warning")
        self.assertEqual(len(warnings), 1)
        self.assertIn("Head role target is 100", warnings[0])
        self.assertIn("now add up to 75", warnings[0])

    def test_a_deactivated_target_no_longer_counts_towards_the_role(self):
        """Forecasts ignore inactive targets, so the comparison does too."""
        targets = self.split_as_viewer()
        ForecastTarget.objects.filter(pk=targets["rep2"].pk).update(is_active=False)
        with self.no_request_cache():
            status = role_targets.status_of(
                ForecastTarget.objects.get(pk=targets["rep"].pk)
            )
        self.assertEqual((status["current"], status["members"]), (Decimal("75"), 3))

    # ----- the target list shows a role total as one row, not one row per user

    def open_list(self, user, **params):
        """The target list for the fixture's period and type, as the page loads it."""
        from django.urls import reverse

        self.grant(user, "view_forecasttarget")
        self.client.force_login(user)
        query = {"forecast_type": self.forecast_type.pk, "period": self.period.pk}
        query.update(params)
        return self.client.get(
            reverse("forecast:forecast_target_list_view"), query, HTTP_HX_REQUEST="true"
        ).content.decode()

    def one_off_target(self, user):
        """A target set for one user on their own, with no role total."""
        return ForecastTarget.objects.create(
            assigned_to=user,
            period=self.period,
            forcasts_type=self.forecast_type,
            target_amount=5,
            company=self.company,
        )

    def test_list_shows_one_row_for_a_role_total_and_leaves_its_users_out(self):
        """Four users behind one total: a single Role Targets row, not four list rows."""
        self.split_as_viewer()
        self.one_off_target(self.peer)
        html = self.open_list(self.viewer)
        self.assertIn('id="role-targets-section"', html)
        self.assertEqual(html.count('class="border-t border-dark-50 rt-batch-row"'), 1)
        self.assertIn("Head", html)
        self.assertIn("Includes roles below", html)
        self.assertIn("Matches", html)
        # the individual list keeps the one-off target and drops the split's users
        self.assertIn("Other", html)  # the one-off target's role
        self.assertNotIn("rep2", html)
        self.assertIn("Individual Targets", html)

    def test_a_role_total_that_no_longer_adds_up_says_so_on_its_row(self):
        """Edit one user's target and the role total's row shows it does not match."""
        targets = self.split_as_viewer()
        ForecastTarget.objects.filter(pk=targets["rep"].pk).update(target_amount=32)
        html = self.open_list(self.viewer)
        self.assertIn("Does not match", html)
        self.assertIn("107", html)

    def test_a_list_without_role_totals_looks_exactly_as_before(self):
        """Only individual targets: no Role Targets section at all."""
        self.one_off_target(self.peer)
        html = self.open_list(self.viewer)
        self.assertNotIn("role-targets-section", html)
        self.assertNotIn("Individual Targets", html)
        self.assertIn("Other", html)

    def test_searching_lists_plain_user_rows_so_anyone_can_be_found(self):
        """A search for a user inside a role total finds them, with no grouped section."""
        self.split_as_viewer()
        html = self.open_list(self.viewer, search="rep2")
        self.assertNotIn("role-targets-section", html)
        self.assertIn("rep2", html)

    def role_total_users(self, user, batch, **params):
        """Open the users behind a role total, as its arrow does."""
        from django.urls import reverse

        self.grant(user, "view_forecasttarget")
        self.client.force_login(user)
        query = {"batch": batch}
        query.update(params)
        return self.client.get(
            reverse("forecast:forecast_role_target_users"),
            query,
            HTTP_HX_REQUEST="true",
        ).content.decode()

    def test_opening_a_role_total_lists_its_users_with_their_actions(self):
        """Each user with their target, role, and edit and delete."""
        targets = self.split_as_viewer()
        batch = role_targets.note_of(targets["rep"])["batch"]
        self.grant(self.viewer, "change_forecasttarget", "delete_forecasttarget")
        html = self.role_total_users(self.viewer, batch)
        self.assertIn("rt-users-row", html)
        for name in ("head", "manager", "rep", "rep2"):
            self.assertIn(f">{name}<", html)
        self.assertEqual(html.count("forecast-target-update-form-view/"), 4)
        self.assertEqual(html.count("forecast-target-delete-view/"), 4)
        self.assertNotIn("Loading more users", html)

    def test_a_large_role_total_loads_its_users_a_page_at_a_time(self):
        """26 users: 20 first, then the last 6 as plain rows."""
        targets = self.split_as_viewer()
        note = role_targets.note_of(targets["rep"])
        for index in range(22):
            user = self.make_user(f"extra{index:02d}", self.rep.role)
            ForecastTarget.objects.create(
                assigned_to=user,
                period=self.period,
                forcasts_type=self.forecast_type,
                target_amount=1,
                company=self.company,
                additional_info={"role_target": note},
            )
        first = self.role_total_users(self.viewer, note["batch"])
        self.assertEqual(first.count('<td class="py-2 pe-3"'), 20)
        self.assertIn("Loading more users", first)
        self.assertIn("page=2", first)
        second = self.role_total_users(self.viewer, note["batch"], page=2)
        self.assertEqual(second.count('<td class="py-2 pe-3"'), 6)
        self.assertNotIn("rt-users-row", second)  # rows only, they replace the button
        self.assertNotIn("Loading more users", second)

    def test_a_manager_sees_only_their_own_users_of_a_role_total(self):
        """The boss's share inside the total is not listed or summed for them."""
        targets = self.split_as_viewer()
        batch = role_targets.note_of(targets["rep"])["batch"]
        visible = {self.manager.pk, self.rep.pk, self.rep2.pk}
        (row,) = role_targets.list_batches(
            ForecastTarget, self.period.pk, self.forecast_type.pk, visible
        )
        self.assertEqual((row["members"], row["visible_members"]), (4, 3))
        self.assertEqual(row["visible_current"], Decimal("75"))  # not the whole 100
        self.assertFalse(row["complete"])
        self.assertIsNone(row["matches"])  # no verdict on a sum they cannot see in full
        html = self.role_total_users(self.manager, batch)
        for name in ("manager", "rep", "rep2"):
            self.assertIn(f">{name}<", html)
        self.assertNotIn(">head<", html)

    def test_a_batch_none_of_whose_users_you_may_see_is_not_listed(self):
        """A peer's role total does not appear for someone outside it."""
        self.split_as_viewer()
        self.assertEqual(
            role_targets.list_batches(
                ForecastTarget, self.period.pk, self.forecast_type.pk, {self.peer.pk}
            ),
            [],
        )

    def test_a_malformed_batch_id_returns_nothing(self):
        """No crash, no rows."""
        html = self.role_total_users(self.viewer, "no good; drop")
        self.assertIn("No users to show", html)

    # ----- editing a role total from its row scales every user's target to it

    def test_rescale_keeps_proportions_and_adds_up_exactly(self):
        targets = self.split_as_viewer()
        ForecastTarget.objects.filter(pk=targets["rep"].pk).update(target_amount=40)
        batch = role_targets.note_of(ForecastTarget.objects.get(pk=targets["rep"].pk))[
            "batch"
        ]
        before = {
            t.pk: t.target_amount
            for t in ForecastTarget.objects.filter(is_active=True)
            if role_targets.note_of(t) and role_targets.note_of(t)["batch"] == batch
        }
        total_before = sum(before.values())
        new_total = Decimal("1234.56")
        count = role_targets.rescale_total(
            ForecastTarget, batch, new_total, self.viewer
        )
        self.assertEqual(count, len(before))
        after = {t.pk: t for t in ForecastTarget.objects.filter(pk__in=before)}
        self.assertEqual(sum(t.target_amount for t in after.values()), new_total)
        big = max(before, key=before.get)
        self.assertEqual(max(after.values(), key=lambda t: t.target_amount).pk, big)
        note = role_targets.note_of(after[big])
        self.assertEqual(Decimal(note["total"]), new_total)
        self.assertIn("previous_total", note)
        self.assertGreater(total_before, 0)

    def test_edit_form_opens_and_saves_for_an_allowed_user(self):
        from django.urls import reverse

        targets = self.split_as_viewer()
        batch = role_targets.note_of(ForecastTarget.objects.get(pk=targets["rep"].pk))[
            "batch"
        ]
        self.grant(self.viewer, "change_forecasttarget")
        self.client.force_login(self.viewer)
        url = reverse("forecast:forecast_role_total_edit")
        page = self.client.get(url, {"batch": batch}, HTTP_HX_REQUEST="true")
        self.assertEqual(page.status_code, 200)
        self.assertIn("Edit Role Target", page.content.decode())
        bad = self.client.post(
            url, {"batch": batch, "total": "0"}, HTTP_HX_REQUEST="true"
        )
        self.assertIn("greater than zero", bad.content.decode())
        ok = self.client.post(
            url, {"batch": batch, "total": "500"}, HTTP_HX_REQUEST="true"
        )
        self.assertEqual(ok.status_code, 200)
        current = role_targets.current_sum(ForecastTarget, batch)
        self.assertEqual(current, Decimal("500"))
        denied = self.client.get(url, {"batch": "nope"}, HTTP_HX_REQUEST="true")
        self.assertEqual(denied.status_code, 403)

    def test_editing_one_role_inside_a_total_scales_only_its_users(self):
        targets = self.split_as_viewer()
        batch = role_targets.note_of(ForecastTarget.objects.get(pk=targets["rep"].pk))[
            "batch"
        ]
        members = [
            t
            for t in ForecastTarget.objects.filter(is_active=True)
            if role_targets.note_of(t) and role_targets.note_of(t)["batch"] == batch
        ]
        role_id = members[0].assigned_to.role_id
        in_role = [t for t in members if t.assigned_to.role_id == role_id]
        outside = {
            t.pk: t.target_amount for t in members if t.assigned_to.role_id != role_id
        }
        batch_total_before = sum(t.target_amount for t in members)
        self.assertTrue(in_role)
        new = Decimal("777.77")
        role_targets.rescale_total(
            ForecastTarget, batch, new, self.viewer, role_id=role_id
        )
        in_after = ForecastTarget.objects.filter(pk__in=[t.pk for t in in_role])
        self.assertEqual(sum(t.target_amount for t in in_after), new)
        for pk, amount in outside.items():
            self.assertEqual(ForecastTarget.objects.get(pk=pk).target_amount, amount)
        everyone = ForecastTarget.objects.filter(pk__in=[t.pk for t in members])
        new_sum = sum(t.target_amount for t in everyone)
        self.assertNotEqual(new_sum, batch_total_before)
        # the role total followed, because it matched before
        self.assertEqual(Decimal(role_targets.note_of(everyone[0])["total"]), new_sum)
