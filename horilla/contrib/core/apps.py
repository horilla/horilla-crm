"""
Horilla Core App configuration.
Handles app setup, demo data, and scheduler,signals and menu initialization.
"""

# Standard library imports
import logging

# First party imports (Horilla)
from horilla.apps import AppLauncher
from horilla.utils.translation import gettext_lazy as _

logger = logging.getLogger(__name__)


class CoreConfig(AppLauncher):
    """
    Configuration for the Horilla Core application.
    Includes URL registration and optional scheduler,signals and menu startup.
    """

    default = True

    default_auto_field = "django.db.models.BigAutoField"
    name = "horilla.contrib.core"
    label = "core"
    verbose_name = _("Core System")

    url_prefix = ""
    url_module = "horilla.contrib.core.urls"
    url_namespace = "core"

    auto_import_modules = [
        "registration",
        "signals",
        "scheduler",
        "login_history",
        "menu",
        "onboarding",
    ]

    celery_schedule_module = "celery_schedules"

    demo_data = {
        "files": [
            (1, "load_data/company.json"),
            (2, "load_data/role.json"),
            (3, "load_data/department.json"),
            (4, "load_data/users.json"),
            (13, "load_data/team_role.json"),
            (14, "load_data/customer_role.json"),
            (15, "load_data/partner_role.json"),
            (16, "load_data/business_hour.json"),
        ],
        # Optional fields (key & display_name will be auto-generated if not provided)
        "key": "users_count",
        "display_name": _("Users"),
        "order": 1,
    }

    def get_api_paths(self):
        """
        Return API path configurations for this app.

        Returns:
            list: List of dictionaries containing path configuration
        """
        return [
            {
                "pattern": "core/",
                "view_or_include": "horilla.contrib.core.api.urls",
                "name": "core_api",
                "namespace": "core",
            }
        ]

    def ready(self):
        super().ready()
        try:
            from django.apps import apps as django_apps

            if django_apps.ready:
                from horilla.extension.card.bootstrap import apply_card_extensions
                from horilla.extension.detail.bootstrap import apply_detail_extensions
                from horilla.extension.filter.bootstrap import apply_filter_extensions
                from horilla.extension.forms.bootstrap import apply_form_extensions
                from horilla.extension.kanban.bootstrap import apply_kanban_extensions
                from horilla.extension.list.bootstrap import apply_list_extensions
                from horilla.extension.nav.bootstrap import apply_nav_extensions
                from horilla.extension.tab.bootstrap import apply_tab_extensions

                apply_form_extensions()
                apply_filter_extensions()
                apply_nav_extensions()
                apply_list_extensions()
                apply_card_extensions()
                apply_kanban_extensions()
                apply_detail_extensions()
                apply_tab_extensions()
        except Exception as exc:
            logger.warning(
                "Extension bootstrap skipped or failed: %s",
                exc,
                exc_info=True,
            )
