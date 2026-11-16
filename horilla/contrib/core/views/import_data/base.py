"""
Shared imports, constants, and base views for Horilla data import.

Used by step1, step2, step3, step4, aux_views.
"""

# Standard library imports
import logging

from horilla.apps import apps

# First party imports (Horilla)
from horilla.auth.mixins import LoginRequiredMixin
from horilla.contrib.generics.views import HorillaNavView, HorillaTabView
from horilla.registry.feature import FEATURE_REGISTRY, get_feature_options
from horilla.urls import reverse_lazy
from horilla.utils.decorators import (
    htmx_required,
    method_decorator,
    permission_required_or_denied,
)
from horilla.utils.translation import gettext_lazy as _
from horilla.views.generic import TemplateView

logger = logging.getLogger(__name__)

# Fields to exclude from import mapping/validation (used across all import views)
IMPORT_EXCLUDED_FIELDS = [
    "id",
    "created_at",
    "updated_at",
    "is_active",
    "additional_info",
    "company",
    "created_by",
    "updated_by",
    "history",
]


def get_import_excluded_fields(model):
    """
    Fields left out of import mapping: the shared list above plus the model's own
    ``exclude_fields`` option for the "import_data" feature, set when the model is
    registered (see ``register_model_for_feature(..., options=...)``).
    """
    options = get_feature_options("import_data", model)
    return IMPORT_EXCLUDED_FIELDS + list(options.get("exclude_fields", []))


def get_model_verbose_name(module_name, app_label):
    """Get the verbose name of a model from its module name and app label."""
    if not module_name or not app_label:
        return module_name or ""

    try:
        model = apps.get_model(app_label, module_name)
        return model._meta.verbose_name
    except (LookupError, AttributeError):
        # If model not found, return the module_name as fallback
        return module_name


class ImportView(LoginRequiredMixin, TemplateView):
    """A generic class-based view for rendering the Horilla import data page."""

    template_name = "import/import_view.html"


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied("core.can_view_horilla_import"),
    name="dispatch",
)
class ImportNavbar(LoginRequiredMixin, HorillaNavView):
    """
    Navbar for the Horilla import data page.
    """

    nav_title = _("Import Data")
    nav_description = _("Bulk import records from a file.")
    main_url = reverse_lazy("core:import_view")
    nav_width = False
    all_view_types = False
    recently_viewed_option = False
    filter_option = False
    one_view_only = True
    reload_option = False
    search_option = False


@method_decorator(
    permission_required_or_denied("core.can_view_horilla_import"),
    name="dispatch",
)
class ImportTabView(LoginRequiredMixin, HorillaTabView):
    """
    A generic class-based view for rendering the company information settings page.
    """

    view_id = "import-data-view"
    background_class = "bg-primary-100 rounded-md"
    tabs = [
        {
            "title": _("Import Data"),
            "url": reverse_lazy("core:import_data"),
            "target": "import-view-content",
            "id": "import-view",
        },
        {
            "title": _("Import History"),
            "url": reverse_lazy("core:import_history_view"),
            "target": "import-history-view-content",
            "id": "import-history-view",
        },
    ]


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied("core.can_view_horilla_import"),
    name="dispatch",
)
class ImportDataView(TemplateView):
    """View to handle data import process."""

    template_name = "import/import_data.html"

    def get(self, request, *args, **kwargs):
        """Set session import config for single or multi import and render import page."""
        context = self.get_context_data(**kwargs)

        single_import = request.GET.get("single_import", "false").lower() == "true"
        model_name = request.GET.get("model_name", "")
        app_label = self.request.GET.get("app_label", "")

        if single_import:
            request.session.pop("import_data", None)
            request.session["import_config"] = {
                "single_import": True,
                "model_name": model_name,
                "app_label": app_label,
            }
            context["selected_module"] = model_name
        else:
            request.session.pop("import_config", None)
            import_data = request.session.get("import_data", {})
            if import_data:
                context["selected_module"] = import_data.get("module", "")
                context["selected_import_name"] = import_data.get("import_name", "")
                context["selected_filename"] = import_data.get("original_filename", "")

        context["single_import"] = single_import
        return self.render_to_response(context)

    def get_context_data(self, **kwargs):
        """Add available import modules to context."""
        context = super().get_context_data(**kwargs)
        context["modules"] = self.get_available_models()
        return context

    def get_available_models(self):
        """Retrieve available models for import based on registry and session config."""
        single_import = self.request.GET.get("single_import", "false").lower() == "true"
        import_config = self.request.session.get("import_config", {})
        model_name = self.request.GET.get("model_name", "") or import_config.get(
            "model_name", ""
        )
        app_label = self.request.GET.get("app_label", "") or import_config.get(
            "app_label", ""
        )

        models = []

        try:
            import_models = FEATURE_REGISTRY.get("import_models", [])

            if single_import and model_name and app_label:
                # Look up model in registry for single import
                model = next(
                    (
                        m
                        for m in import_models
                        if m._meta.model_name == model_name.lower()
                        and m._meta.app_label == app_label
                    ),
                    None,
                )
                if model:
                    add_perm = f"{model._meta.app_label}.add_{model._meta.model_name}"
                    if self.request.user.has_perm(add_perm):
                        models.append(self._format_model_info(model))

            else:
                # Return only models the user has add permission for
                for model in import_models:
                    add_perm = f"{model._meta.app_label}.add_{model._meta.model_name}"
                    if self.request.user.has_perm(add_perm):
                        models.append(self._format_model_info(model))
        except Exception as e:
            logger.error("Error getting available models: %s", e)

        return models

    def _format_model_info(self, model):
        return {
            "name": model.__name__,
            "label": model._meta.verbose_name,
            "app_label": model._meta.app_label,
            "module": model.__module__,
        }
