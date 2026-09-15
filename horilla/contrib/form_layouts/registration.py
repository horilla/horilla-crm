"""
Feature registration for the form layouts app.
"""

# First party imports (Horilla)
from horilla.registry.feature import register_feature

register_feature(
    "form_layouts",
    "form_layout_models",
    auto_register_all=False,
)
