"""Cadence tab view for generic platform record detail pages."""

# Standard library imports
from functools import cached_property

from horilla.apps import apps

# First party imports (Horilla)
from horilla.auth.mixins import LoginRequiredMixin
from horilla.contrib.core.models import HorillaContentType
from horilla.contrib.core.utils import is_owner
from horilla.contrib.generics.views import HorillaListView, HorillaNavView, HorillaView
from horilla.urls import reverse
from horilla.utils.decorators import htmx_required, method_decorator
from horilla.utils.translation import gettext_lazy as _
from horilla.web import Http404

# Local imports
from .. import services
from ..followup_types import get_followup_type_label
from ..models import CadenceEnrollment
from ..signals import ensure_initial_followups_for_instance
from .enrollment import can_change_record


class CadenceRecordMixin:
    """
    Shared by the tab, navbar and list of the Cadence tab.

    ``register_cadence_tab`` creates one subclass of each per model and sets
    ``record_app_label`` / ``record_model_name`` / ``record_url_name``.
    """

    record_app_label = None
    record_model_name = None
    record_url_name = None

    def _check_view_permission(self, model, pk):
        user = self.request.user
        app_label = model._meta.app_label
        model_name = model._meta.model_name
        view_perm = f"{app_label}.view_{model_name}"
        view_own_perm = f"{app_label}.view_own_{model_name}"
        return user.has_perm(view_perm) or (
            user.has_perm(view_own_perm) and is_owner(model, pk)
        )

    def dispatch(self, request, *args, **kwargs):
        """Resolve the record and check view permission."""
        try:
            model = apps.get_model(self.record_app_label, self.record_model_name)
        except LookupError as exc:
            raise Http404(_("Invalid model for cadence tab.")) from exc
        obj = model.objects.filter(pk=kwargs.get("pk")).first()
        if not obj:
            raise Http404(_("Object not found."))
        if not self._check_view_permission(model, obj.pk):
            raise Http404(_("You don't have permission to view this item."))
        self._record_obj = obj
        self._record_model = model
        return super().dispatch(request, *args, **kwargs)

    def _record_url(self, suffix=""):
        """URL of this tab (or its ``_nav`` / ``_list`` part) for the current record."""
        return reverse(
            f"cadences:{self.record_url_name}{suffix}",
            kwargs={"pk": self._record_obj.pk},
        )


@method_decorator(htmx_required, name="dispatch")
class CadenceRecordTabView(LoginRequiredMixin, CadenceRecordMixin, HorillaView):
    """Cadence tab: loads the navbar and the list."""

    template_name = "cadence_record_tab.html"
    view_id = "cadence-record-tab"

    @property
    def nav_url(self):
        """Navbar URL of this record."""
        return self._record_url("_nav")

    @property
    def list_url(self):
        """List URL of this record."""
        return self._record_url("_list")


@method_decorator(htmx_required, name="dispatch")
class CadenceRecordNavbar(LoginRequiredMixin, CadenceRecordMixin, HorillaNavView):
    """Title, description, reload, column option and Enroll button of the Cadence tab."""

    nav_title = _("Cadences")
    model_name = "CadenceEnrollment"
    model_app_label = "cadences"
    nav_width = False
    all_view_types = False
    recently_viewed_option = False
    filter_option = False
    one_view_only = True
    border_enabled = False
    search_option = False
    enable_actions = True

    @cached_property
    def nav_description(self):
        """Description naming the record's model."""
        return _("View and manage the cadences this %(name)s is enrolled in.") % {
            "name": str(self._record_model._meta.verbose_name).lower()
        }

    @cached_property
    def new_button(self):
        """Enroll button, for users who may change the record."""
        if not can_change_record(
            self.request.user, self._record_model, self._record_obj
        ):
            return None
        return {
            "url": reverse(
                "cadences:cadence_enroll_modal",
                kwargs={
                    "app_label": self._record_model._meta.app_label,
                    "record_model": self._record_model._meta.model_name,
                    "record_pk": self._record_obj.pk,
                },
            ),
            "title": _("Enroll"),
            "attrs": {"id": "cadence-enroll-btn"},
        }

    @cached_property
    def actions(self):
        """Only the column option applies to this list."""
        return [
            {
                "action": _("Add Column to List"),
                "attrs": f"""
                    hx-get="{reverse('generics:column_selector')}?app_label=cadences&model_name=CadenceEnrollment"
                    hx-include="#active-list-url-name"
                    onclick="openModal()"
                    hx-target="#modalBox"
                    hx-swap="innerHTML"
                """,
            }
        ]


@method_decorator(htmx_required, name="dispatch")
class CadenceRecordListView(LoginRequiredMixin, CadenceRecordMixin, HorillaListView):
    """
    List of the Cadence tab: one row per enrollment of the record, newest first,
    so earlier runs stay visible.
    """

    model = CadenceEnrollment
    view_id = "cadence-record-tab-list"
    filterset_class = None
    columns = [
        (_("Cadence Name"), "cadence_name_col"),
        (_("Start Date"), "started_at"),
        (_("Completed Date"), "completed_at_col"),
        (_("Enrolled By"), "enrolled_by_col"),
        (_("Un-enrolled Date"), "unenrolled_at_col"),
        (_("Cadence Status"), "cadence_status_col"),
        (_("Member Status"), "member_status_col"),
        (_("Last Follow-up"), "last_followup"),
    ]
    bulk_select_option = False
    bulk_update_option = False
    bulk_export_option = False
    save_to_list_option = False
    no_record_section = True
    no_record_fit_height = False
    no_record_msg = _("This record is not enrolled in any cadence yet.")
    enable_quick_filters = False
    enable_sorting = False
    # Access is checked on the record itself in dispatch(), not per enrollment row.
    owner_filtration = False
    action_method = "unenroll_action_col"
    _record_tab_queryset = None

    def dispatch(self, request, *args, **kwargs):
        """Reloads go back to this same URL."""
        self.main_url = request.path
        self.search_url = request.path
        return super().dispatch(request, *args, **kwargs)

    def get_queryset(self):
        if self._record_tab_queryset is not None:
            return self._record_tab_queryset
        try:
            # Creates the automatic enrollments for cadences whose conditions match.
            ensure_initial_followups_for_instance(self._record_obj)
        except Exception:
            pass
        content_type = HorillaContentType.objects.get_for_model(self._record_model)
        self._record_tab_queryset = (
            CadenceEnrollment.all_objects.filter(
                content_type=content_type, object_id=self._record_obj.pk
            )
            .select_related("cadence", "created_by")
            .order_by("-started_at", "-id")
        )
        return self._record_tab_queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        for enrollment in context.get("queryset", []):
            summary = services.latest_followup_summary(enrollment)
            if summary:
                kind, status = summary
                enrollment.last_followup = f"{self._type_label(kind)} - {status}"
            else:
                enrollment.last_followup = "—"
        return context

    @staticmethod
    def _type_label(kind):
        builtin = {"task": _("Task"), "log_call": _("Call"), "email": _("Email")}
        if kind in builtin:
            return builtin[kind]
        # A delivery channel follow-up: the channel's label.
        return get_followup_type_label(kind)
