"""
Helper methods for horilla.contrib.generics.

Provides dynamic form resolution and other utilities used by generic views.
"""

# First party imports (Horilla)
from horilla.contrib.core.mixins import OwnerQuerysetMixin
from horilla.contrib.generics.related_fields import resolve_field_path

# Local imports
from .forms import HorillaModelForm


def get_dynamic_form_for_model(model):
    """Return a dynamic ModelForm class for the given model with owner queryset support."""
    _model = model  # capture explicitly before class definition

    class ResolvedDynamicForm(OwnerQuerysetMixin, HorillaModelForm):
        """Dynamic ModelForm for the specified model, inheriting from OwnerQuerysetMixin and HorillaModelForm."""

        class Meta:
            """Meta class for the dynamic form, specifying the model and fields to include/exclude."""

            model = _model  # use the captured local variable
            fields = "__all__"
            exclude = [
                "created_at",
                "updated_at",
                "created_by",
                "updated_by",
                "additional_info",
            ]

    return ResolvedDynamicForm


def get_condition_value_display(model_cls, field_name, value):
    """
    Return a human-readable text for a stored condition ``value``.

    A relation stores the related record's pk and a choice field stores the
    choice key; show the record's name or the choice label instead. Any other
    value, or one that can't be resolved, is returned unchanged.
    """
    if not model_cls or not field_name or not value:
        return value
    field = resolve_field_path(model_cls, field_name)
    if field is None:
        return value

    related_model = getattr(field, "related_model", None)
    if getattr(field, "is_relation", False) and related_model:
        related = related_model.objects.filter(pk=value).first()
        return str(related) if related is not None else value

    for key, label in getattr(field, "choices", None) or []:
        if str(key) == str(value):
            return str(label)
    return value
