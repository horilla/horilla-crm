"""
A generic class-based view for rendering the home page.
"""

# Standard library imports
import logging

# First party imports (Horilla)
from horilla.auth.mixins import LoginRequiredMixin
from horilla.contrib.generics.views import (
    HorillaListView,
    HorillaModalDetailView,
    HorillaNavView,
    HorillaSingleDeleteView,
    HorillaSingleFormView,
)
from horilla.urls import reverse_lazy
from horilla.utils.decorators import (
    htmx_required,
    method_decorator,
    permission_required_or_denied,
)
from horilla.utils.functional import cached_property  # type: ignore
from horilla.utils.translation import gettext_lazy as _
from horilla.views.generic import TemplateView
from horilla.web import HttpResponse, ScriptResponse

# Local imports
from ..filters import HolidayFilter
from ..forms import HolidayForm
from ..models import Holiday

logger = logging.getLogger(__name__)


@method_decorator(htmx_required, name="dispatch")
@method_decorator(permission_required_or_denied("core.view_holiday"), name="dispatch")
class HolidayView(LoginRequiredMixin, TemplateView):
    """
    TemplateView for holiday view.
    """

    template_name = "settings/holiday.html"


@method_decorator(htmx_required, name="dispatch")
@method_decorator(permission_required_or_denied("core.view_holiday"), name="dispatch")
class HolidayNavbar(LoginRequiredMixin, HorillaNavView):
    """
    Navbar for the holidays tab, providing search for holidays.
    """

    nav_title = _("Holidays")
    nav_description = _("Manage the holidays observed by your company.")
    search_url = reverse_lazy("core:holiday_list_view")
    main_url = reverse_lazy("core:holiday_view")
    filterset_class = HolidayFilter
    model_name = "Holiday"
    model_app_label = "core"
    nav_width = False
    one_view_only = True
    all_view_types = False
    filter_option = False
    reload_option = False
    search_push_url = False

    @cached_property
    def new_button(self):
        """
        Get the configuration for the "Add Holidays" button.
        """
        if self.request.user.has_perm("core.add_holiday"):
            return {
                "url": reverse_lazy("core:holiday_create_form"),
                "title": _("Add"),
            }
        return None


@method_decorator(htmx_required, name="dispatch")
@method_decorator(permission_required_or_denied("core.view_holiday"), name="dispatch")
class HolidayListView(LoginRequiredMixin, HorillaListView):
    """
    List View for holiday list.
    """

    model = Holiday
    view_id = "holiday-list-view"
    filterset_class = HolidayFilter
    filter_panel_option = False
    search_url = reverse_lazy("core:holiday_list_view")
    main_url = reverse_lazy("core:holiday_view")
    store_ordered_ids = True
    list_column_visibility = False
    bulk_update_option = False

    @cached_property
    def no_record_add_button(self):
        """
        Get the configuration for the "Add" button when no record exist.
        """
        if self.request.user.has_perm("core.add_holiday"):
            return {
                "url": f"""{reverse_lazy("core:holiday_create_form")}?new=true""",
                "attrs": 'id="holiday-create"',
            }
        return None

    columns = ["name", "start_date", "end_date", "is_recurring"]

    @cached_property
    def col_attrs(self):
        """
        Get the column attributes for the list view.
        """
        query_params = {}
        if "section" in self.request.GET:
            query_params["section"] = self.request.GET.get("section")
        query_string = self.request.session.get(self.ordered_ids_key, [])
        attrs = {}
        if self.request.user.has_perm("core.view_holiday"):
            attrs = {
                "hx-get": f"{{get_detail_url}}?instance_ids={query_string}",
                "hx-target": "#detailModalBox",
                "hx-swap": "innerHTML",
                "hx-push-url": "false",
                "hx-on:click": "openDetailModal();",
                "style": "cursor:pointer",
                "class": "hover:text-primary-600",
            }
        return [
            {
                "name": {
                    **attrs,
                }
            }
        ]

    actions = [
        {
            "action": "Edit",
            "src": "assets/icons/edit.svg",
            "img_class": "w-4 h-4 flex gap-4",
            "permission": "core.change_holiday",
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
            "permission": "core.delete_holiday",
            "attrs": """
                hx-post="{get_delete_url}"
                hx-target="#modalBox"
                hx-swap="innerHTML"
                hx-trigger="click"
                hx-vals='{{"check_dependencies": "false"}}'
                onclick="openModal()"
            """,
        },
    ]


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied("core.delete_holiday", modal=True),
    name="dispatch",
)
class HolidayDeleteView(LoginRequiredMixin, HorillaSingleDeleteView):
    """
    Delete View for Holiday
    """

    model = Holiday

    def get_post_delete_response(self):
        """
        Get the response after deleting a holiday.
        """

        return HttpResponse(
            "<script>$('#reloadHolidayButton').click();closeDeleteModeModal();closeDetailModal();</script>"
        )


@method_decorator(htmx_required, name="dispatch")
class HolidayFormView(LoginRequiredMixin, HorillaSingleFormView):
    """
    Holiday Create/Update View
    """

    model = Holiday
    form_class = HolidayForm
    view_id = "holiday-form-view"
    full_width_fields = ["name", "weekly_days"]
    return_response = ScriptResponse(
        close=True,
        reload=True,
        extra="$('#detailViewReloadButton').click();$('#tab-holidays-view').click();",
    )

    @cached_property
    def form_url(self):
        """Form URL for holiday"""

        pk = self.kwargs.get("pk") or self.request.GET.get("id")
        if pk:
            return reverse_lazy("core:holiday_update_form", kwargs={"pk": pk})
        return reverse_lazy("core:holiday_create_form")

    def get_initial(self):
        """
        Get initial data for holiday form.
        """

        initial = super().get_initial()

        toggle = self.request.GET.get("toggle_all_users")

        if toggle == "true":
            current = self.request.GET.get("all_users", "").lower()
            current_recurring = self.request.GET.get("is_recurring", "").lower()

            initial["all_users"] = current in ["true", "on", "1"]
            initial["is_recurring"] = current_recurring in ["true", "on", "1"]
            initial["frequency"] = self.request.GET.get("frequency", "")
            initial["monthly_repeat_type"] = self.request.GET.get(
                "monthly_repeat_type", ""
            )
            initial["yearly_repeat_type"] = self.request.GET.get(
                "yearly_repeat_type", ""
            )

        elif hasattr(self, "object") and self.object:
            initial["all_users"] = self.object.all_users
            initial["is_recurring"] = self.object.is_recurring
            initial["frequency"] = getattr(self.object, "frequency", "")
            initial["monthly_repeat_type"] = getattr(
                self.object, "monthly_repeat_type", ""
            )
            initial["yearly_repeat_type"] = getattr(
                self.object, "yearly_repeat_type", ""
            )

        else:
            initial["all_users"] = True
            initial["is_recurring"] = False
            initial["frequency"] = ""
            initial["monthly_repeat_type"] = ""
            initial["yearly_repeat_type"] = ""

        protected = {
            "all_users",
            "is_recurring",
            "frequency",
            "monthly_repeat_type",
            "yearly_repeat_type",
        }
        for key, value in self.request.GET.items():
            if key not in protected:
                initial[key] = value

        return initial


@method_decorator(htmx_required, name="dispatch")
@method_decorator(permission_required_or_denied("core.view_holiday"), name="dispatch")
class HolidayDetailView(LoginRequiredMixin, HorillaModalDetailView):
    """
    detail view of page
    """

    model = Holiday
    title = _("Details")
    header = {
        "title": "name",
        "subtitle": "",
        "avatar": "get_avatar",
    }

    body = [
        "start_date",
        "end_date",
        ("specific_users", "specific_users_enable"),
        ("is_recurring", "is_recurring_holiday"),
    ]

    actions = [
        {
            "action": "Delete",
            "src": "assets/icons/a4.svg",
            "img_class": "svg-themed w-3 h-3",
            "permission": "core.delete_holiday",
            "attrs": """
                    class="outline outline-1 outline-offset-[-1px] outline-primary-600 rounded-md hover:bg-primary-300 transition duration-300 text-primary-600 w-24 justify-center bg-[white] flex items-center gap-2 disabled:cursor-not-allowed cursor-pointer text-xs px-4 py-2"
                    hx-post="{get_delete_url}"
                    hx-target="#modalBox"
                    hx-swap="innerHTML"
                    hx-trigger="click"
                    hx-vals='{{"check_dependencies": "false"}}'
                    onclick="openModal()"
                """,
        },
        {
            "action": "Edit",
            "src": "assets/icons/edit_white.svg",
            "img_class": "w-3 h-3 flex gap-4 filter brightness-0 invert",
            "permission": "core.change_holiday",
            "attrs": """
                class="w-24 justify-center px-4 py-2 bg-primary-600 text-white rounded-md text-xs flex items-center gap-2 hover:bg-primary-800 transition duration-300 disabled:cursor-not-allowed cursor-pointer"
                hx-get="{get_edit_url}"
                hx-target="#modalBox"
                hx-swap="innerHTML"
                onclick="openModal();"
            """,
        },
    ]
