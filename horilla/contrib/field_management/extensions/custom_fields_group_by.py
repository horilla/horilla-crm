"""
Group Kanban boards, Group By lists and charts by Single Choice custom fields.

Those views group by a real model column and ask the view for it through
``get_group_field()``; the rows are then filtered / counted on that column.
A custom field lives in ``CustomFieldValue`` instead, so this module supplies
what the views need, without touching them:

- ``CustomFieldGroupByListExtension`` / the per-view Kanban extensions
  (``_inherit_list`` / ``_inherit_kanban``): list ``cf_*`` fields as grouping
  choices, answer ``get_group_field()`` for them, annotate the queryset with
  the field's value (so ``filter(cf_1=...)`` and ``values("cf_1")`` work) and
  save the value when a Kanban card is moved (``persist_group_value()``).
- ``CustomFieldKanbanSettingsExtension`` (``_inherit_view``): lists the fields
  in the Kanban / Group By settings form and saves the choice, because
  ``KanbanGroupBy.save()`` only accepts real model fields.

Only Single Choice fields can group (a Multiple Choice value belongs to
several columns at once).
"""

import json
import logging

from django.apps import apps as django_apps
from django.db.models import Case, CharField, OuterRef, Subquery, Value, When

from horilla.contrib.core.models import HorillaContentType, KanbanGroupBy
from horilla.contrib.field_management.models import CustomFieldValue
from horilla.contrib.field_management.utils.custom_fields import (
    custom_field_form_name,
    get_custom_field_definitions,
    is_custom_field_name,
    safe_custom_field_label,
    save_custom_field_values,
)
from horilla.extension.list import ListExtension
from horilla.extension.view import ViewExtension
from horilla.utils.translation import gettext_lazy as _
from horilla.web import ScriptResponse

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _group_definitions(model):
    """``{cf_<id>: definition}`` for the model's Single Choice custom fields."""
    try:
        return {
            custom_field_form_name(d): d
            for d in get_custom_field_definitions(model)
            if d.field_type == "single_choice"
        }
    except Exception:
        logger.exception("custom_fields: could not load group-by fields")
        return {}


def _allowed_names(model, exclude, include):
    """Group-by-able ``cf_*`` names, honouring exclude/include field settings."""
    return [
        name
        for name in _group_definitions(model)
        if name not in (exclude or []) and (include is None or name in include)
    ]


def _split_names(value):
    names = [n.strip() for n in (value or "").split(",") if n.strip()]
    return names or None


def _settings_model(data):
    """The model named by the Kanban / Group By settings request, or None."""
    app_label = data.get("app_label")
    model_name = data.get("model") or data.get("model_name")
    if not app_label or not model_name:
        return None
    try:
        return django_apps.get_model(app_label, model_name)
    except (LookupError, ValueError):
        return None


class _CustomChoiceField:
    """What Horilla's grouping code reads from a model field: choices and a label."""

    null = False
    is_relation = False

    def __init__(self, name, definition):
        self.name = name
        self.verbose_name = str(safe_custom_field_label(definition))
        self.choices = [(c, c) for c in definition.get_choices_list()] + [
            (None, str(_("None")))
        ]


def _annotate(queryset, model, names):
    """Annotate ``cf_*`` columns holding each record's selected choice."""
    definitions = _group_definitions(model)
    content_type = HorillaContentType.objects.get_for_model(model)
    for name in names:
        defn = definitions.get(name)
        choices = defn.get_choices_list() if defn else []
        if not choices:
            continue
        raw = f"_{name}_raw"
        stored = CustomFieldValue.objects.filter(
            content_type=content_type,
            field_definition=defn,
            object_id=OuterRef("pk"),
        ).values("value_text")[:1]
        whens = [
            When(
                **{f"{raw}__in": [choice, json.dumps([choice], ensure_ascii=False)]},
                then=Value(choice),
            )
            for choice in choices
        ]
        queryset = queryset.annotate(**{raw: Subquery(stored)}).annotate(
            **{name: Case(*whens, default=Value(None), output_field=CharField())}
        )
    return queryset


# ---------------------------------------------------------------------------
# Kanban / Group By views
# ---------------------------------------------------------------------------


class _GroupMethods:
    """
    Method template shared by the Group By, Chart and Kanban extensions below.

    Never registered or subclassed: the functions are copied by reference into
    each extension's namespace (same pattern as ``_MultiStepFormMethods`` in
    ``custom_fields_forms.py``), and the framework rebinds their ``super()``
    to the composed view.
    """

    def _cf_kind(self):
        from horilla.contrib.generics.views.chart import HorillaChartView
        from horilla.contrib.generics.views.groupby import HorillaGroupByView
        from horilla.contrib.generics.views.kanban import HorillaKanbanView

        if isinstance(self, HorillaChartView):
            return "chart"
        if isinstance(self, HorillaKanbanView):
            return "kanban"
        if isinstance(self, HorillaGroupByView):
            return "group_by"
        return None

    def _cf_group_names(self):
        """The ``cf_*`` fields this request currently groups by."""
        kind = self._cf_kind()
        if kind is None or not getattr(self, "model", None):
            return []
        try:
            if kind == "kanban":
                current = [self.get_group_by_field()]
            elif kind == "chart":
                current = [self.get_group_by_field()]
                chart_type = (
                    self.request.GET.get("chart_type") or self.default_chart_type
                ).lower()
                if chart_type in self.STACKED_CHART_TYPES:
                    current.append(self.get_stack_by_field(current[0], chart_type))
            else:
                current = self.get_group_by_fields()
        except Exception:
            logger.exception("custom_fields: could not resolve the grouping field")
            return []
        return [name for name in current if is_custom_field_name(name)]

    def get_group_field(self, field_name):
        """Grouping field for a custom field, or the parent view's field."""
        definition = _group_definitions(self.model).get(field_name)
        if definition is None:
            return super().get_group_field(field_name)
        return _CustomChoiceField(field_name, definition)

    def persist_group_value(self, item, group_by):
        """Save a card's custom-field group, or the parent view's value."""
        if not is_custom_field_name(group_by):
            return super().persist_group_value(item, group_by)
        save_custom_field_values(
            self.model,
            item.pk,
            {group_by: getattr(item, group_by, None) or ""},
            company=getattr(item, "company", None),
        )
        return None

    def _get_allowed_group_by_fields(self, view_type="kanban"):
        allowed = list(super()._get_allowed_group_by_fields(view_type=view_type))
        exclude, include = self._get_kanban_exclude_include_fields(view_type)
        allowed += [
            name
            for name in _allowed_names(self.model, exclude, include)
            if name not in allowed
        ]
        return allowed

    def get_group_by_field_choices(self):
        """Group-by choices, including the visible custom fields."""
        choices = list(super().get_group_by_field_choices())
        known = {value for value, _label in choices}
        exclude, include = self._get_kanban_exclude_include_fields("group_by")
        definitions = _group_definitions(self.model)
        for name in _allowed_names(self.model, exclude, include):
            if name not in known and self._is_field_visible_for_group_by(name):
                choices.append((name, safe_custom_field_label(definitions[name])))
        return choices

    def get_chart_dimension_choices(self):
        """Chart dimension choices, including the visible custom fields."""
        choices = list(super().get_chart_dimension_choices())
        known = {value for value, _label in choices}
        exclude, include = self._get_kanban_exclude_include_fields()
        definitions = _group_definitions(self.model)
        for name in _allowed_names(self.model, list(exclude), include):
            if name not in known:
                choices.append((name, str(safe_custom_field_label(definitions[name]))))
        return choices

    def get_queryset(self):
        """Queryset annotated with the custom fields used for grouping."""
        queryset = super().get_queryset()
        names = self._cf_group_names()
        if not names:
            return queryset
        return _annotate(queryset, self.model, names)


def _methods(*names):
    return {name: _GroupMethods.__dict__[name] for name in names}


_SHARED = (
    "_cf_kind",
    "_cf_group_names",
    "get_group_field",
    "persist_group_value",
    "_get_allowed_group_by_fields",
    "get_queryset",
)

# Group By and Chart views resolve ``_inherit_list`` extensions through the
# shared ``HorillaListView`` base.
CustomFieldGroupByListExtension = type(
    "CustomFieldGroupByListExtension",
    (ListExtension,),
    {
        "__module__": __name__,
        "__doc__": "Group By lists and charts grouped by Single Choice custom fields.",
        "_inherit_list": "horilla.contrib.generics.views.list.HorillaListView",
        **_methods(
            *_SHARED, "get_group_by_field_choices", "get_chart_dimension_choices"
        ),
    },
)

_KANBAN_REGISTERED = set()


def register_kanban_extensions():
    """
    Register the Kanban extension for every concrete kanban view.

    ``_inherit_kanban`` targets one concrete view (the shared base is not
    allowed) and resolves per class, so each kanban view in every installed
    app gets its own registration. Runs from a pre-compose hook, once all
    views are imported, and is safe to run repeatedly.
    """
    from horilla.contrib.generics.views.kanban import HorillaKanbanView
    from horilla.extension.kanban import KanbanExtension

    pending = list(HorillaKanbanView.__subclasses__())
    while pending:
        view_class = pending.pop()
        pending.extend(view_class.__subclasses__())
        path = f"{view_class.__module__}.{view_class.__name__}"
        if (
            path in _KANBAN_REGISTERED
            or not getattr(view_class, "model", None)
            or getattr(view_class, "__horilla_kanban_composed__", False)
            or view_class.__module__.startswith("horilla.extension")
        ):
            continue
        _KANBAN_REGISTERED.add(path)
        type(
            f"CustomFieldKanbanGroupBy{view_class.__name__}",
            (KanbanExtension,),
            {
                "__module__": __name__,
                "__doc__": "Kanban boards grouped by Single Choice custom fields.",
                "_inherit_kanban": path,
                **_methods(*_SHARED),
            },
        )


def _install_kanban_hook():
    from horilla.extension._pre_compose_hooks import register_pre_compose_hook

    # Runs at the start of Horilla's first compose step, after every app's
    # views are imported and before kanban extensions are composed.
    register_pre_compose_hook("forms", register_kanban_extensions)


_install_kanban_hook()
register_kanban_extensions()


# ---------------------------------------------------------------------------
# Kanban / Group By settings
# ---------------------------------------------------------------------------


class CustomFieldKanbanSettingsExtension(ViewExtension):
    """List custom fields in Kanban / Group By settings and save the choice."""

    _inherit_view = (
        "horilla.contrib.generics.views.helpers.kanban_groupby.HorillaKanbanGroupByView"
    )

    def get_form(self, form_class=None):
        """Settings form, with custom fields available as group-by choices."""
        form = super().get_form(form_class)
        data = self.request.POST if self.request.method == "POST" else self.request.GET
        model = _settings_model(data)
        if model is None or "field_name" not in form.fields:
            return form
        exclude = _split_names(data.get("exclude_fields")) or []
        include = _split_names(data.get("include_fields"))
        definitions = _group_definitions(model)
        choices = list(form.fields["field_name"].choices)
        known = {value for value, _label in choices}
        for name in _allowed_names(model, exclude, include):
            if name not in known:
                choices.append((name, safe_custom_field_label(definitions[name])))
        form.fields["field_name"].choices = choices
        return form

    def post(self, request, *args, **kwargs):
        """``KanbanGroupBy`` only accepts real fields, so ``cf_*`` is stored directly."""
        name = request.POST.get("field_name")
        model = _settings_model(request.POST)
        if not is_custom_field_name(name) or model is None:
            return super().post(request, *args, **kwargs)
        exclude = _split_names(request.POST.get("exclude_fields")) or []
        include = _split_names(request.POST.get("include_fields"))
        if name not in _allowed_names(model, exclude, include):
            return super().post(request, *args, **kwargs)

        view_type = request.POST.get("view_type") or "kanban"
        lookup = {
            "model_name": model.__name__,
            "app_label": model._meta.app_label,
            "user": request.user,
            "view_type": view_type,
        }
        KanbanGroupBy.all_objects.filter(**lookup).delete()
        KanbanGroupBy.all_objects.bulk_create(
            [KanbanGroupBy(field_name=name, **lookup)]
        )
        return ScriptResponse(close=True, reload=True)
