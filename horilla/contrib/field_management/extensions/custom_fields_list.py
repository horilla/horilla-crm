"""
Inject custom fields into list views through ListExtension (_inherit_list),
targeting the shared ``HorillaListView`` base class.

Every concrete list view (``LeadListView``, ``OpportunityListView``, etc.,
across every CRM app, present and future) inherits ``get_context_data`` from
this one base class. Registering ``_inherit_list`` against each concrete
subclass individually would require custom_fields to know every list view
in every app in advance — the opposite of "generic, not hardcoded."

``horilla.extension.list.resolve.resolve_list_view_class`` — the same
resolver every ``_inherit_list`` registration goes through at
``as_view()`` time — checks an exact match for the concrete class first,
then falls back to checking each base class in the concrete class's MRO. A
registration on ``HorillaListView`` here is therefore picked up by every
concrete list view automatically, the same way registering directly on
``LeadListView`` would be for just that one view. See
``horilla/extension/list/resolve.py``'s ``_resolve_via_base_class`` and
``docs/horilla/extension/list/inherit.md`` for the mechanism.
"""

from horilla.contrib.field_management.hooks.filter import (
    relabel_applied_filter_slot_rows,
)
from horilla.contrib.field_management.hooks.list import (
    attach_custom_fields_to_list_context,
)
from horilla.extension.list import ListExtension


class CustomFieldListContextExtension(ListExtension):
    """Attach custom-field values and sorting exclusions to every list view."""

    _inherit_list = "horilla.contrib.generics.views.list.HorillaListView"

    def get_context_data(self, **kwargs):
        """Attach custom-field values and sort exclusions to list context."""
        context = super().get_context_data(**kwargs)
        try:
            attach_custom_fields_to_list_context(self, context)
        except Exception:
            import logging

            logging.getLogger(__name__).exception(
                "custom_fields: could not attach list custom fields"
            )
        return context


class CustomFieldListAppliedFilterExtension(ListExtension):
    """Show a custom field's real name on the list's applied-filter chip."""

    _inherit_list = "horilla.contrib.generics.views.list.HorillaListView"

    def get_context_data(self, **kwargs):
        """Relabel ``cf_*`` applied-filter rows after the list builds them."""
        context = super().get_context_data(**kwargs)
        try:
            relabel_applied_filter_slot_rows(self.request, self.model, context)
        except Exception:
            import logging

            logging.getLogger(__name__).exception(
                "custom_fields: could not relabel applied filters"
            )
        return context
