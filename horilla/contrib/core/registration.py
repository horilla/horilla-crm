"""
Feature registration for Horilla Core app.
"""

# First party imports (Horilla)
from horilla.auth.models import User
from horilla.contrib.generics.related_fields import register_default_related_fields
from horilla.registry.asset_registry import register_html
from horilla.registry.feature import register_feature, register_models_for_feature

# Local imports
from .models import Company, Department, Role

register_html(
    "inject_html/rtl_assets.html",
    slot="head_end",
    priority=90,
)

register_html(
    "inject_html/rtl_assets.html",
    slot="head_end",
    priority=90,
    page="login",
)


register_models_for_feature(
    models=[
        Company,
        Department,
        Role,
        User,
    ],
    all=True,
    exclude=["dashboard_component", "report_choices"],
)


register_feature(
    "template_reverse",
    "template_reverse_models",
)

# Models registered for "delete_dependency" are ignored when a record is deleted:
# they are not listed as dependencies and are not offered for reassigning.
register_feature(
    "delete_dependency",
    "delete_dependency_models",
    auto_register_all=False,
)

register_models_for_feature(
    models=[
        ("core", "FieldPermission"),
        ("core", "DetailFieldVisibility"),
        ("core", "QuickFilter"),
        ("core", "ImportHistory"),
        ("core", "FiscalYear"),
        ("core", "FiscalYearInstance"),
        ("core", "Quarter"),
        ("core", "Period"),
    ],
    features=["delete_dependency"],
)

# Related fields offered behind any relation to a user (owner, created by, ...)
# in reports, the filter panel and condition builders.
register_default_related_fields(
    "core",
    "horillauser",
    [
        "department",
        "role",
        "company",
    ],
)
