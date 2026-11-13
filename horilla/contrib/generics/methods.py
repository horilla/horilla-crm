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


def group_label_with_company(request, related_item, show_company=True):
    """Label for a Kanban/group-by column built from a related record.

    With "all companies" enabled, company-scoped records (e.g. lead stages) of
    different companies can share a name, so the company name is appended to tell
    the columns apart.
    """
    label = str(related_item)
    session = getattr(request, "session", None)
    if (
        not show_company
        or session is None
        or not session.get("show_all_companies", False)
    ):
        return label
    if getattr(related_item, "company_id", None):
        return f"{label} ({related_item.company})"
    return label


def group_order_by(request, related_model):
    """Ordering for the columns of a Kanban/group-by built from a related model.

    With "all companies" enabled, columns are grouped by company first so one
    company's columns stay together instead of interleaving by ``order``.
    """
    field_names = [f.name for f in related_model._meta.fields]
    ordering = ["order"] if "order" in field_names else ["pk"]
    session = getattr(request, "session", None)
    if (
        session is not None
        and session.get("show_all_companies", False)
        and "company" in field_names
    ):
        ordering = ["company__name", "company_id"] + ordering
    return ordering
