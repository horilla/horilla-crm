"""
Version information for the form layouts app.
"""

# First party imports (Horilla)
from horilla.utils.translation import gettext_lazy as _

__version__ = "1.0.0"
__module_name__ = "Form Layouts"
__release_date__ = ""
__description__ = _(
    "Choose which fields appear on the create form of opted-in models, and in "
    "what order, per company."
)
__icon__ = ""

__1_0_0__ = _(
    "Register form layouts as a self-contained contrib feature. Lead and "
    "Opportunity opt in through the feature registry. Per-company "
    "FormLayoutField rows hide optional fields and reorder the single-page "
    "create form; a model with a saved layout opens that form instead of the "
    "multi-step wizard. Edit forms are never changed."
)
