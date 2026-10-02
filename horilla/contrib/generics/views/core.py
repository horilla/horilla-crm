"""
Generic views for Horilla, including base view, tab view, history section, and dynamic create view.
"""

# Standard library imports
import logging
from functools import update_wrapper

# Third-party imports (Django)
from django import forms
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.paginator import Paginator
from django.template.loader import render_to_string

from horilla.apps import apps
from horilla.contrib.core.models import ActiveTab
from horilla.contrib.core.utils import get_field_permissions_for_model
from horilla.core.exceptions import ImproperlyConfigured

# First party imports (Horilla)
from horilla.db import models
from horilla.shortcuts import render
from horilla.utils.decorators import htmx_required, method_decorator
from horilla.utils.html import escapejs
from horilla.utils.translation import gettext_lazy as _
from horilla.views.generic import DetailView, FormView, TemplateView
from horilla.web import HttpResponse, RefreshResponse

# Local imports
from ..forms import HorillaHistoryForm, HorillaModelForm
from ..templatetags.horilla_tags.history_display import collapse_redundant_history

logger = logging.getLogger(__name__)


class HorillaView(TemplateView):
    """
    A generic class-based view for rendering templates with context data.
    """

    template_name = "base.html"
    list_url: str = ""
    kanban_url: str = ""
    group_by_url: str = ""
    card_url: str = ""
    timeline_url: str = ""
    split_view_url: str = ""
    chart_url: str = ""
    nav_url: str = ""
    view_id: str = ""
    custom_layouts: dict = {}

    def _validate_required_urls(self):
        """Ensure nav_url and at least one view URL are configured in child class."""
        nav_url = getattr(self, "nav_url", "") or ""
        if not nav_url:
            raise ImproperlyConfigured(
                f"{self.__class__.__name__} must define a non-empty nav_url."
            )

        view_urls = {
            "list_url": getattr(self, "list_url", "") or "",
            "kanban_url": getattr(self, "kanban_url", "") or "",
            "group_by_url": getattr(self, "group_by_url", "") or "",
            "card_url": getattr(self, "card_url", "") or "",
            "timeline_url": getattr(self, "timeline_url", "") or "",
            "split_view_url": getattr(self, "split_view_url", "") or "",
            "chart_url": getattr(self, "chart_url", "") or "",
        }
        custom_urls = {
            name: (layout or {}).get("url", "")
            for name, layout in (getattr(self, "custom_layouts", None) or {}).items()
        }
        if not any(view_urls.values()) and not any(custom_urls.values()):
            raise ImproperlyConfigured(
                f"{self.__class__.__name__} must define at least one non-empty view URL: "
                "list_url, kanban_url, group_by_url, card_url, timeline_url, "
                "split_view_url, chart_url, or an entry in custom_layouts."
            )

    def dispatch(self, request, *args, **kwargs):
        """Validate URL configuration before handling request."""
        self._validate_required_urls()
        return super().dispatch(request, *args, **kwargs)

    def get_layout_url(self):
        """Resolve which layout URL should be loaded based on request."""
        layout = self.request.GET.get("layout")

        mapping = {
            "kanban": self.kanban_url,
            "group_by": self.group_by_url,
            "card": self.card_url,
            "timeline": self.timeline_url,
            "split_view": self.split_view_url,
            "chart": self.chart_url,
            "list": self.list_url,
        }
        for name, layout_config in (
            getattr(self, "custom_layouts", None) or {}
        ).items():
            mapping[name] = (layout_config or {}).get("url", "")

        # If valid layout and URL exists
        if layout in mapping and mapping[layout]:
            return mapping[layout]

        # No explicit layout requested: honor the view's configured default
        # (kept in sync with HorillaNavView.default_layout so the toggle
        # icon and the loaded content agree).
        default_layout = getattr(self, "default_layout", None)
        if default_layout in mapping and mapping[default_layout]:
            return mapping[default_layout]

        # Fallback logic (same as your template)
        if not self.list_url and self.kanban_url:
            return self.kanban_url

        return self.list_url

    def get_context_data(self, **kwargs):
        """Add nav/list/kanban/group_by/card/split_view URLs and filter_form trigger to template context."""
        context = super().get_context_data(**kwargs)
        filter_form = self.request.headers.get("HX-Trigger")
        if filter_form == "filter-form":
            context["filter_form"] = filter_form
        context["nav_url"] = self.nav_url
        context["list_url"] = self.list_url
        context["kanban_url"] = self.kanban_url
        context["group_by_url"] = self.group_by_url
        context["card_url"] = getattr(self, "card_url", "") or ""
        context["timeline_url"] = getattr(self, "timeline_url", "") or ""
        context["split_view_url"] = getattr(self, "split_view_url", "") or ""
        context["chart_url"] = getattr(self, "chart_url", "") or ""
        context["custom_layouts"] = getattr(self, "custom_layouts", None) or {}
        context["layout_url"] = self.get_layout_url()
        context["view_id"] = getattr(self, "view_id", "") or ""
        return context


@method_decorator(htmx_required, name="dispatch")
class HorillaTabView(TemplateView):
    """
    Generic TabView.

    ``as_view`` resolves ``_inherit_tab`` extensions for the concrete subclass
    on each request (same late-binding idea as list/detail composition).
    Third-party apps should override ``get_tabs`` via ``TabExtension``.
    """

    view_id = ""
    template_name = "tab_view.html"
    tabs: list = []
    background_class = ""
    background_color = ""
    tab_class = ""
    is_detail_view = False

    @classmethod
    def as_view(cls, **initkwargs):
        """Return a callable that resolves ``_inherit_tab`` extensions per request."""
        if getattr(cls, "__horilla_tab_composed__", False):
            return super().as_view(**initkwargs)

        base_view = super().as_view(**initkwargs)

        def view(request, *args, **kwargs):
            from horilla.extension.tab.resolve import resolve_tab_view_class

            resolved = resolve_tab_view_class(cls)
            if resolved is not cls:
                if (
                    getattr(view, "_extended_handler", None) is None
                    or getattr(view, "_extended_cls", None) is not resolved
                ):
                    view._extended_cls = resolved
                    view._extended_handler = resolved.as_view(**initkwargs)
                return view._extended_handler(request, *args, **kwargs)
            return base_view(request, *args, **kwargs)

        update_wrapper(view, base_view)
        view.view_class = cls
        view.view_initkwargs = initkwargs
        return view

    def get_tabs(self):
        """
        Return the tab list for this view.

        Prefers instance-assigned ``tabs`` (e.g. from ``setup`` /
        ``_prepare_detail_tabs``), then subclass ``tabs`` (list or
        ``@cached_property`` / property). ``_inherit_tab`` extensions should
        override this method.
        """
        if "tabs" in self.__dict__:
            return self.__dict__["tabs"]

        for cls in type(self).mro():
            if cls is HorillaTabView:
                break
            raw = cls.__dict__.get("tabs", None)
            if raw is None:
                continue
            if isinstance(raw, list):
                return list(raw)
            if hasattr(raw, "__get__"):
                value = raw.__get__(self, type(self))
                return list(value) if isinstance(value, list) else value

        default = type(self).__dict__.get("tabs")
        if isinstance(default, list):
            return list(default)
        return list(getattr(HorillaTabView, "tabs", []) or [])

    def get_context_data(self, **kwargs):
        """Add active_target, tabs, view_id, and tab styling to context."""
        context = super().get_context_data(**kwargs)
        if self.request and getattr(self.request, "user", None):
            active_tab = ActiveTab.objects.filter(
                created_by=self.request.user, path=self.request.path
            ).first()
            if active_tab:
                context["active_target"] = active_tab.tab_target
        context["tabs"] = self.get_tabs()
        context["view_id"] = self.view_id
        context["background_class"] = self.background_class
        context["background_color"] = self.background_color
        context["tab_class"] = self.tab_class
        context["is_detail_view"] = self.is_detail_view
        return context


@method_decorator(htmx_required, name="dispatch")
class HorillaHistorySectionView(DetailView):
    """View for displaying object history/audit trail in detail views."""

    template_name = "history_tab.html"
    context_object_name = "obj"
    paginate_by = 10
    filter_form_class = HorillaHistoryForm

    def dispatch(self, request, *args, **kwargs):
        """Resolve object and return HX-Refresh on error; otherwise dispatch."""
        try:
            self.object = self.get_object()
        except Exception as e:
            messages.error(self.request, e)
            return RefreshResponse(request)
        return super().dispatch(request, *args, **kwargs)

    def get_history_date(self, timestamp):
        """
        Return the day a history timestamp falls on in the timezone its time is
        shown in (the user's, else the company's), not the stored UTC day, so an
        entry is never grouped under the day before or after the one it shows.
        """
        # Lazy import: avoid cycles with extension bootstrap / generics imports.
        from horilla.extension.formatting import get_datetime_formatter

        user = self.request.user
        company = getattr(self.request, "active_company", None) or getattr(
            user, "company", None
        )
        local_timestamp = get_datetime_formatter()._apply_timezone(
            timestamp, user=user, company=company
        )
        return local_timestamp.date()

    def get_context_data(self, **kwargs):
        """Add paginated history by date, filter form, and filter_applied to context."""
        context = super().get_context_data(**kwargs)
        context["model_name"] = self.model._meta.model_name
        histories = self.get_object().full_histories

        history_by_date = []
        date_dict = {}
        for entry in histories:
            date_key = self.get_history_date(entry.timestamp)
            if date_key not in date_dict:
                date_dict[date_key] = []
            date_dict[date_key].append(entry)

        sorted_dates = sorted(date_dict.keys(), reverse=True)
        history_by_date = [(date, date_dict[date]) for date in sorted_dates]
        filter_form = self.filter_form_class(self.request.GET)
        filter_applied = False
        if self.request.GET:
            filter_applied = any(
                self.request.GET.get(field) not in [None, "", "all"]
                for field in filter_form.fields
            )

            if filter_form.is_valid() and filter_applied:
                history_by_date = filter_form.apply_filter(history_by_date)

        paginator = Paginator(history_by_date, self.paginate_by)
        page_number = self.request.GET.get("page", 1)
        page_obj = paginator.get_page(page_number)
        # Collapse the shown days here rather than in the template, so a day
        # left with nothing to show (e.g. only saves that changed no visible
        # field) is dropped instead of rendering as an empty group.
        shown_days = []
        for date_key, entries in page_obj.object_list:
            entries = collapse_redundant_history(entries)
            if entries:
                shown_days.append((date_key, entries))
        page_obj.object_list = shown_days

        context["page_obj"] = page_obj
        context["actions"] = [str(entry).split()[0].lower() for entry in histories]
        context["filter_form"] = filter_form
        context["filter_applied"] = filter_applied

        return context

    def get(self, request, *args, **kwargs):
        """Render history tab or filter form partial when show_filter=true and HX-Request."""
        self.object = self.get_object()
        context = self.get_context_data(**kwargs)
        if request.GET.get("show_filter") == "true" and request.headers.get(
            "HX-Request"
        ):
            return HttpResponse(
                render_to_string(
                    "partials/history_filter_form.html",
                    {"form": context["filter_form"], "request": request},
                    request=request,
                )
            )

        return self.render_to_response(context)


@method_decorator(htmx_required, name="dispatch")
class HorillaDynamicCreateView(LoginRequiredMixin, FormView):
    """
    View to handle dynamic creation of related models
    """

    template_name = "dynamic_form_view.html"
    target_model = None
    field_names = None

    def get_permission_from_mapping(self):
        """Get custom permission from dynamic_create_field_mapping if provided"""
        permission_param = self.request.GET.get("permission")

        if permission_param:
            return [p.strip() for p in permission_param.split(",") if p.strip()]

        return None

    def get_model_and_fields(self):
        """
        Resolve and return a model and optional field list from kwargs/GET params.

        Returns `(model, field_names)` or `(None, None)` if the model cannot be found.
        """
        app_label = self.kwargs.get("app_label")
        model_name = self.kwargs.get("model_name")
        fields_param = self.request.GET.get("fields", "")

        field_names = None
        if fields_param and fields_param.lower() not in ["none", ""]:
            field_names = [f.strip() for f in fields_param.split(",") if f.strip()]

        try:
            model = apps.get_model(app_label, model_name)
            return model, field_names
        except LookupError:
            logger.warning("Model %s.%s not found", app_label, model_name)
            messages.error(self.request, f"Model {app_label}.{model_name} not found")
            return None, None

    def _modal_close_with_message_response(self):
        """Return an HttpResponse that reloads messages and closes the dynamic modal."""
        response = HttpResponse(
            """<div></div>
            <script>
                setTimeout(function() {
                    $('#reloadMessagesButton').click();
                    closeDynamicModal();
                }, 50);
            </script>"""
        )
        response["Cache-Control"] = "no-cache, no-store, must-revalidate"
        response["Pragma"] = "no-cache"
        response["Expires"] = "0"
        return response

    def dispatch(self, request, *args, **kwargs):
        """Resolve target model and fields; validate and check add permission; then dispatch."""
        # Initialize model + fields once
        self.target_model, self.field_names = self.get_model_and_fields()

        if not self.target_model:
            messages.error(self.request, _("Invalid model or fields"))
            return self._modal_close_with_message_response()

        # Validate field names against the model
        if self.field_names:
            valid_field_names = {f.name for f in self.target_model._meta.get_fields()}
            invalid_fields = [f for f in self.field_names if f not in valid_field_names]
            if invalid_fields:
                messages.error(
                    self.request,
                    f"Some fields are not valid: {', '.join(invalid_fields)}.",
                )
                return self._modal_close_with_message_response()

        custom_perms = self.get_permission_from_mapping()

        if custom_perms:
            permissions = custom_perms
        else:
            app_label = self.target_model._meta.app_label
            model_name = self.target_model._meta.model_name
            permissions = [f"{app_label}.add_{model_name}"]

        if not any(request.user.has_perm(perm) for perm in permissions):
            return render(request, "403.html", {"modal": True})

        return super().dispatch(request, *args, **kwargs)

    def get_form_class(self):
        """Return a dynamic ModelForm class for target_model and optional field_names."""
        target_model, field_names = self.target_model, self.field_names

        class DynamicCreateForm(HorillaModelForm):
            """Dynamically generated form for creating related objects."""

            class Meta:
                """Meta options for DynamicCreateForm."""

                model = target_model
                fields = (
                    field_names if field_names and field_names != [""] else "__all__"
                )
                exclude = [
                    "created_at",
                    "updated_at",
                    "created_by",
                    "updated_by",
                    "additional_info",
                ]
                widgets = {
                    field.name: forms.DateInput(attrs={"type": "date"})
                    for field in target_model._meta.fields
                    if isinstance(field, models.DateField)
                }

        return DynamicCreateForm

    def get_full_width_fields(self):
        """Get full width fields from URL parameter."""
        full_width_param = self.request.GET.get("full_width_fields", "")
        full_width_fields = []
        if full_width_param and full_width_param.lower() not in ["none", ""]:
            clean_param = full_width_param.split("?")[0]  # Remove anything after ?
            full_width_fields = [f.strip() for f in clean_param.split(",") if f.strip()]
        return full_width_fields

    def get_context_data(self, **kwargs):
        """Add form_title, target_field, form_url, full_width_fields, and field_permissions to context."""
        context = super().get_context_data(**kwargs)
        if self.target_model:
            context["form_title"] = f"Create {self.target_model._meta.verbose_name}"
            context["target_field"] = self.request.GET.get("target_field")
            query_string = self.request.GET.urlencode()
            context["form_url"] = (
                f"{self.request.path}?{query_string}"
                if query_string
                else self.request.path
            )
            context["full_width_fields"] = self.get_full_width_fields()

            # Add field permissions to context
            field_permissions = get_field_permissions_for_model(
                self.request.user, self.target_model
            )
            context["field_permissions"] = field_permissions
        else:
            context["field_permissions"] = {}
        return context

    def get_initial_values_from_mapping(self):
        """Get initial values from dynamic_create_field_mapping if available"""
        initial_values = {}

        # Get initial values from URL parameters with initial_ prefix
        for key, value in self.request.GET.items():
            if key.startswith("initial_"):
                field_name = key.replace("initial_", "", 1)
                try:
                    # Try to convert to number if possible
                    if value.isdigit():
                        initial_values[field_name] = int(value)
                    elif value.replace(".", "", 1).isdigit():
                        initial_values[field_name] = float(value)
                    else:
                        initial_values[field_name] = value
                except (ValueError, AttributeError):
                    initial_values[field_name] = value

        return initial_values

    def get_form_kwargs(self):
        """Pass full_width_fields and field_permissions to the form"""
        kwargs = super().get_form_kwargs()
        kwargs["full_width_fields"] = self.get_full_width_fields()

        # Add field permissions to form kwargs
        if self.target_model:
            field_permissions = get_field_permissions_for_model(
                self.request.user, self.target_model
            )
            kwargs["field_permissions"] = field_permissions

        # Add initial values from mapping
        initial_values = self.get_initial_values_from_mapping()
        if initial_values:
            if "initial" not in kwargs:
                kwargs["initial"] = {}
            kwargs["initial"].update(initial_values)

        return kwargs

    def form_valid(self, form):
        """Save the new instance and return script to add option to target select and close modal."""

        instance = form.save(commit=False)
        instance.created_by = self.request.user
        instance.updated_by = self.request.user
        instance.company = form.cleaned_data.get("company") or (
            getattr(self.request, "active_company", None) or self.request.user.company
        )
        instance.save()
        form.save_m2m()

        target_field = self.request.GET.get("target_field")

        instance_str = escapejs(str(instance))  # Escape for JavaScript

        return HttpResponse(
            f"""
                <script>
                    var targetSelect = document.querySelector('select[name="{target_field}"]');
                    if (targetSelect) {{
                        var newOption = new Option('{instance_str}', '{instance.pk}', true, true);
                        targetSelect.add(newOption);

                        // Trigger change event if using Select2
                        if (window.$ && $(targetSelect).hasClass('js-example-basic-single')) {{
                            $(targetSelect).trigger('change');
                        }}
                    }}

                    closeDynamicModal();
                </script>
            """
        )

    def form_invalid(self, form):
        """Show error message and re-render form with validation errors."""
        messages.error(self.request, _("Please correct the errors below."))
        return super().form_invalid(form)
