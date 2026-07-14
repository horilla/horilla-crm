"""
Bot Rule builder views: Flow CRUD, plus a node/edge editor for each flow.
"""

# Standard library imports
import logging
from functools import cached_property

# Third-party imports (Django)
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db import models
from django.shortcuts import get_object_or_404, render
from django.template.loader import render_to_string
from django.utils.html import format_html
from django.utils.safestring import mark_safe
from django.views import View

from horilla.contrib.generics.views import (
    HorillaListView,
    HorillaNavView,
    HorillaSingleDeleteView,
    HorillaSingleFormView,
    HorillaView,
)

# First party imports (Horilla)
from horilla.urls import reverse_lazy
from horilla.utils.decorators import (
    htmx_required,
    method_decorator,
    permission_required_or_denied,
)
from horilla.utils.translation import gettext_lazy as _
from horilla.web import HttpResponse

# Local imports
from ..filters import WhatsAppBotRuleFilter
from ..forms import (
    WhatsAppBotRuleEdgeForm,
    WhatsAppBotRuleForm,
    WhatsAppBotRuleNodeForm,
)
from ..models import (
    WhatsAppBotRule,
    WhatsAppBotRuleEdge,
    WhatsAppBotRuleNode,
    WhatsAppFlow,
)

logger = logging.getLogger(__name__)


@method_decorator(
    permission_required_or_denied(["whatsapp.view_whatsappbotrule"]),
    name="dispatch",
)
class WhatsAppBotRuleView(LoginRequiredMixin, HorillaView):
    """Page shell for Bot Rule management."""

    template_name = "whatsapp_bot_rule/whatsapp_bot_rule_view.html"
    nav_url = reverse_lazy("whatsapp:whatsapp_bot_rule_navbar_view")
    list_url = reverse_lazy("whatsapp:whatsapp_bot_rule_list_view")


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied(["whatsapp.view_whatsappbotrule"]),
    name="dispatch",
)
class WhatsAppBotRuleNavbar(LoginRequiredMixin, HorillaNavView):
    """Navbar for Bot Rule management."""

    nav_title = _("Bot Rules")
    search_url = reverse_lazy("whatsapp:whatsapp_bot_rule_list_view")
    main_url = reverse_lazy("whatsapp:whatsapp_bot_rule_view")
    model_name = "WhatsAppBotRule"
    model_app_label = "whatsapp"
    nav_width = False
    gap_enabled = False
    all_view_types = False
    one_view_only = True
    filter_option = False
    reload_option = False
    border_enabled = False

    @cached_property
    def new_button(self):
        """Return the new button configuration if the user has permission."""
        if self.request.user.has_perm("whatsapp.add_whatsappbotrule"):
            return {
                "url": f"""{reverse_lazy("whatsapp:whatsapp_bot_rule_create_view")}""",
                "target": "#modalBox",
                "onclick": "openModal();",
                "attrs": {"id": "whatsapp-bot-rule-create"},
            }
        return None


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied(["whatsapp.view_whatsappbotrule"]),
    name="dispatch",
)
class WhatsAppBotRuleListView(LoginRequiredMixin, HorillaListView):
    """List view of Bot Rules."""

    model = WhatsAppBotRule
    view_id = "whatsapp-bot-rule-list"
    search_url = reverse_lazy("whatsapp:whatsapp_bot_rule_list_view")
    main_url = reverse_lazy("whatsapp:whatsapp_bot_rule_view")
    table_width = False
    table_height_as_class = "h-[calc(_100vh_-_260px_)]"
    list_column_visibility = False
    filterset_class = WhatsAppBotRuleFilter

    columns = [
        "name",
        "account",
        "trigger_type",
        "trigger_keywords",
        "is_active",
        "version",
    ]

    actions = [
        {
            "action": "Edit",
            "src": "assets/icons/edit.svg",
            "img_class": "w-4 h-4",
            "permission": "whatsapp.change_whatsappbotrule",
            "attrs": """
                hx-get="{get_edit_url}"
                hx-target="#modalBox"
                hx-swap="innerHTML"
                onclick="openModal()"
            """,
        },
        {
            "action": "Delete",
            "src": "assets/icons/a4.svg",
            "img_class": "w-4 h-4",
            "permission": "whatsapp.delete_whatsappbotrule",
            "attrs": """
                hx-post="{get_delete_url}"
                hx-target="#modalBox"
                hx-swap="innerHTML"
                hx-trigger="click"
                hx-vals='{{"check_dependencies": "false"}}'
                onclick="openModal()"
            """,
        },
    ]

    def no_record_add_button(self):
        """Return the add button configuration when there are no records."""
        if self.request.user.has_perm("whatsapp.add_whatsappbotrule"):
            return {
                "url": f"""{reverse_lazy("whatsapp:whatsapp_bot_rule_create_view")}""",
                "target": "#modalBox",
                "onclick": "openModal();",
                "attrs": {"id": "whatsapp-bot-rule-create"},
            }
        return None

    @cached_property
    def col_attrs(self):
        """Make the name column open the flow builder."""
        attrs = {}
        if self.request.user.has_perm("whatsapp.change_whatsappbotrule"):
            attrs = {
                "onclick": "window.location.href='{get_builder_url}'",
                "style": "cursor:pointer",
                "class": "hover:text-primary-600",
            }
        return [{"name": attrs}]


@method_decorator(htmx_required, name="dispatch")
class WhatsAppBotRuleFormView(LoginRequiredMixin, HorillaSingleFormView):
    """Create and update form view for a Bot Rule."""

    model = WhatsAppBotRule
    form_class = WhatsAppBotRuleForm
    form_title = _("Bot Rule")
    template_name = "whatsapp_bot_rule/whatsapp_bot_rule_form.html"
    full_width_fields = ["description"]
    hidden_fields = ["version"]
    modal_height = False
    # After creating a rule, open its builder (the rule's detail screen).
    detail_url_name = "whatsapp:whatsapp_bot_rule_builder_view"

    @cached_property
    def form_url(self):
        """Return the create or update URL for the flow form."""
        pk = self.kwargs.get("pk") or self.request.GET.get("id")
        if pk:
            return reverse_lazy(
                "whatsapp:whatsapp_bot_rule_update_view", kwargs={"pk": pk}
            )
        return reverse_lazy("whatsapp:whatsapp_bot_rule_create_view")

    def get(self, request, *args, **kwargs):
        pk = kwargs.get("pk")
        if pk:
            try:
                self.model.all_objects.get(pk=pk)
            except self.model.DoesNotExist:
                messages.error(request, _("The requested data does not exist."))
                return HttpResponse("<script>$('#reloadButton').click();</script>")
        return super().get(request, *args, **kwargs)


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied("whatsapp.delete_whatsappbotrule", modal=True),
    name="dispatch",
)
class WhatsAppBotRuleDeleteView(LoginRequiredMixin, HorillaSingleDeleteView):
    """Delete view for a Bot Rule."""

    model = WhatsAppBotRule

    def get_post_delete_response(self):
        """Return HTMX script to reload the list after successful delete."""
        return HttpResponse("<script>$('#reloadButton').click();</script>")


@method_decorator(
    permission_required_or_denied(["whatsapp.change_whatsappbotrule"]),
    name="dispatch",
)
class WhatsAppBotRuleBuilderView(LoginRequiredMixin, View):
    """
    Server-rendered node/edge editor for one Bot Rule: an ordered list of
    nodes, each editable via a modal form, plus a simple edge editor
    connecting nodes' outgoing branches to their next node.
    """

    template_name = "whatsapp_bot_rule/whatsapp_bot_rule_builder.html"

    def get(self, request, pk):
        flow = get_object_or_404(WhatsAppBotRule, pk=pk)
        nodes = flow.nodes.prefetch_related(
            models.Prefetch(
                "outgoing_edges",
                queryset=WhatsAppBotRuleEdge.objects.select_related("target_node"),
            ),
            models.Prefetch(
                "incoming_edges",
                queryset=WhatsAppBotRuleEdge.objects.select_related("source_node"),
            ),
        )
        nodes = list(nodes)
        view_mode = "diagram" if request.GET.get("view") == "diagram" else "list"
        return render(
            request,
            self.template_name,
            {
                "flow": flow,
                "nodes": nodes,
                "diagram_data": self._diagram_data(nodes),
                "view_mode": view_mode,
            },
        )

    def _diagram_data(self, nodes):
        """Serialize nodes/edges for the client-side diagram layout script."""
        return {
            "nodes": [{"pk": node.pk, "isStart": node.is_start} for node in nodes],
            "edges": [
                {
                    "source": edge.source_node_id,
                    "target": edge.target_node_id,
                    "handle": edge.source_handle or "",
                }
                for node in nodes
                for edge in node.outgoing_edges.all()
            ],
        }


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied(["whatsapp.change_whatsappbotrule"]),
    name="dispatch",
)
class WhatsAppBotRuleNodeFormView(LoginRequiredMixin, HorillaSingleFormView):
    """Create and update form view for a single Bot Rule node."""

    model = WhatsAppBotRuleNode
    form_class = WhatsAppBotRuleNodeForm
    form_title = _("Flow Node")
    template_name = "whatsapp_bot_rule/whatsapp_bot_rule_node_form.html"
    modal_height = False
    modal_height_class = "max-h-[600px]"

    def get_context_data(self, **kwargs):
        import json

        from ..forms import NODE_TYPE_FIELD_GROUPS, RULE_TYPES

        context = super().get_context_data(**kwargs)
        context["node_type_field_groups"] = json.dumps(NODE_TYPE_FIELD_GROUPS)
        context["flow_variable_names"] = json.dumps(
            sorted(self._known_variable_names())
        )
        context["flow_variable_prefixes"] = json.dumps(self._known_variable_prefixes())
        context["rule_types"] = RULE_TYPES
        config = (self.object.config if getattr(self, "object", None) else {}) or {}
        context["field_mapping_rows"] = self._kv_rows("field_mapping", config)
        context["filters_rows"] = self._kv_rows("filters", config)
        context["options_rows"] = self._options_rows(config)
        context["branches_rows"] = self._branches_rows(config)
        return context

    def _kv_rows(self, builder, config):
        """Build {row_id, field_name, value, value_widget_html} for each saved field_mapping/filters entry."""
        content_type_id = config.get("content_type_id") or config.get(
            "_ui_hint_content_type_id"
        )
        options_view = WhatsAppFieldMappingOptionsView()
        model_cls = (
            options_view._resolve_model(content_type_id) if content_type_id else None
        )
        field_choices = options_view._field_choices(model_cls) if model_cls else []

        rows = []
        for row_id, (field_name, value) in enumerate(
            (config.get(builder) or {}).items()
        ):
            rows.append(
                {
                    "row_id": str(row_id),
                    "field_name": field_name,
                    "value": value,
                    "field_choices": field_choices,
                    "value_widget_html": options_view._render_value_widget(
                        model_cls, field_name, builder, str(row_id), value
                    ),
                }
            )
        return rows

    def _options_rows(self, config):
        """Build {row_id, id, label} for each saved button/list option."""
        return [
            {"row_id": str(i), "id": opt.get("id", ""), "label": opt.get("label", "")}
            for i, opt in enumerate(config.get("options") or [])
        ]

    def _branches_rows(self, config):
        """Build {row_id, handle, rules: [...]} for each saved condition branch."""
        rows = []
        for branch_id, branch in enumerate(config.get("branches") or []):
            rules = []
            for rule_id, rule in enumerate(branch.get("rules") or []):
                rules.append(
                    {
                        "row_id": str(rule_id),
                        "type": rule.get("type", ""),
                        "field": rule.get("field") or rule.get("variable", ""),
                        "value": rule.get("value", ""),
                    }
                )
            rows.append(
                {
                    "row_id": str(branch_id),
                    "handle": branch.get("handle", ""),
                    "rules": rules,
                }
            )
        return rows

    def _known_variable_names(self):
        """
        Collect every variable_name this flow's nodes capture (Question,
        Buttons, List), so the node form can suggest {{variables.<name>}}
        tokens instead of the admin having to remember what earlier nodes
        named their captured answers.
        """
        names = set()
        for node in self.flow.nodes.all():
            variable_name = (node.config or {}).get("variable_name")
            if variable_name:
                names.add(variable_name)
        return names

    def _known_variable_prefixes(self):
        """
        Collect every Send Meta Flow node's answers variable_prefix, plus
        whatever field names under that prefix are actually known - tried in
        this order:

        1. Meta's own Flow JSON (via get_flow_field_names), fetched live from
           WhatsApp Manager - the real schema, available even before anyone
           has ever submitted the Flow. Best-effort: a network hiccup, an
           unpublished/data-exchange Flow Meta refuses to hand back, or a
           misconfigured account just means this source contributes nothing,
           not a hard failure for the whole node form.
        2. Every real WhatsAppBotRuleSession.variables this flow has ever
           recorded, for keys under "<prefix>." - ground truth of what a
           completed submission actually contained; catches anything (1)
           missed (e.g. Meta API unreachable right now).
        3. The node's own answer_field_names, if someone filled it in.

        All three merge into one deduped set per prefix.
        """
        from .. import services as whatsapp_services

        result = {}
        flow_ids = set()
        for node in self.flow.nodes.all():
            if node.node_type != "send_meta_flow":
                continue
            config = node.config or {}
            prefix = config.get("variable_prefix") or "meta_flow"
            field_names = {
                name for name in config.get("answer_field_names") or [] if name
            }
            result.setdefault(prefix, set()).update(field_names)
            if config.get("flow_id"):
                flow_ids.add((prefix, config["flow_id"]))

        if not result:
            return {}

        for prefix, meta_flow_pk in flow_ids:
            meta_flow = WhatsAppFlow.objects.filter(pk=meta_flow_pk).first()
            if not meta_flow:
                continue
            try:
                client = whatsapp_services.WhatsAppCloudAPIClient(meta_flow.account)
                result[prefix].update(client.get_flow_field_names(meta_flow.flow_id))
            except Exception:
                logger.warning(
                    "Could not fetch field names for Meta Flow %s from Meta; "
                    "falling back to session-mined/configured names.",
                    meta_flow.flow_id,
                    exc_info=True,
                )

        key_prefixes = tuple(f"{prefix}." for prefix in result)
        for session_variables in self.flow.sessions.values_list("variables", flat=True):
            for key in session_variables or {}:
                if not key.startswith(key_prefixes):
                    continue
                prefix, _dot, field_name = key.partition(".")
                if field_name:
                    result[prefix].add(field_name)

        return {prefix: sorted(names) for prefix, names in result.items()}

    @cached_property
    def flow(self):
        """Return the parent flow, from the node (update) or the query string (create)."""
        pk = self.kwargs.get("pk")
        if pk:
            return get_object_or_404(WhatsAppBotRuleNode, pk=pk).flow
        return get_object_or_404(WhatsAppBotRule, pk=self.request.GET.get("flow"))

    @cached_property
    def form_url(self):
        """
        Return the create or update URL for the node form. The `?flow=`
        query string is appended automatically by HorillaSingleFormView from
        request.GET, so it must NOT be added again here.
        """
        pk = self.kwargs.get("pk")
        if pk:
            return reverse_lazy(
                "whatsapp:whatsapp_bot_rule_node_update_view", kwargs={"pk": pk}
            )
        return reverse_lazy("whatsapp:whatsapp_bot_rule_node_create_view")

    def form_valid(self, form):
        form.instance.flow = self.flow
        response = super().form_valid(form)
        form.apply_handle_renames()
        return response


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied(["whatsapp.change_whatsappbotrule"]),
    name="dispatch",
)
class WhatsAppFieldMappingOptionsView(LoginRequiredMixin, View):
    """
    Backs the field_mapping/filters row builder (htmx-driven).

    - `?content_type_id=<id>&render=field_select&builder=<name>&row_id=<id>`:
      returns the field-name <select> for one row.
    - `?content_type_id=<id>&field_name=<name>&render=value_widget&builder=<name>&row_id=<id>`:
      returns the value widget (choice dropdown, real-record select2 for a
      ForeignKey, plain text, etc.) for that field, so the admin never has
      to guess a raw stored value or a related record's pk.
    - Without `render=...`: legacy JSON API, kept for back-compat.
    """

    _EXCLUDED_FIELDS = {
        "id",
        "created_at",
        "updated_at",
        "created_by",
        "updated_by",
        "additional_info",
        "history",
    }

    def _resolve_model(self, content_type_id):
        from django.apps import apps as django_apps

        from horilla.contrib.core.models import HorillaContentType

        content_type = HorillaContentType.objects.filter(pk=content_type_id).first()
        if not content_type:
            return None
        model_cls = content_type.model_class()
        if model_cls is None:
            try:
                model_cls = django_apps.get_model(
                    content_type.app_label, content_type.model
                )
            except LookupError:
                return None
        return model_cls

    def _field_choices(self, model_cls):
        """Return [{name, label}] for the model's field-name dropdown."""
        # A model can opt specific non-editable fields (e.g. a
        # conversion/status flag meant to be flipped by automation, not
        # hand-edited on a form) into the bot's field list via an
        # `automation_writable_fields = [...]` class attribute - a plain
        # duck-typed convention, so this generic whatsapp app never needs to
        # import or know about any specific app's models. The same attribute
        # can be reused by other automation entry points beyond the bot.
        bot_writable = set(getattr(model_cls, "automation_writable_fields", ()))
        return [
            {"name": f.name, "label": str(f.verbose_name).title()}
            for f in model_cls._meta.get_fields()
            if getattr(f, "concrete", False)
            and (getattr(f, "editable", True) or f.name in bot_writable)
            and f.name not in self._EXCLUDED_FIELDS
        ]

    def get(self, request, *args, **kwargs):
        render_mode = request.GET.get("render")
        if render_mode == "field_select":
            return self._render_field_select(request)
        if render_mode == "value_widget":
            return self._render_value_widget_response(request)
        return self._get_json(request)

    def _get_json(self, request):
        """Legacy JSON API - kept for back-compat with any other caller."""
        from horilla.web import JsonResponse

        content_type_id = request.GET.get("content_type_id")
        field_name = request.GET.get("field_name")

        model_cls = self._resolve_model(content_type_id)
        if not model_cls:
            return JsonResponse({"kind": "text", "fields": []})

        if not field_name:
            return JsonResponse({"fields": self._field_choices(model_cls)})

        try:
            field = model_cls._meta.get_field(field_name)
        except Exception:
            return JsonResponse({"kind": "text"})

        if isinstance(field, (models.ForeignKey, models.ManyToManyField)):
            related_model = field.related_model
            return JsonResponse(
                {
                    "kind": "foreignkey",
                    "select2_url": reverse_lazy(
                        "generics:model_select2",
                        kwargs={
                            "app_label": related_model._meta.app_label,
                            "model_name": related_model._meta.model_name,
                        },
                    ),
                }
            )
        if getattr(field, "choices", None):
            return JsonResponse(
                {
                    "kind": "choice",
                    "choices": [[value, str(label)] for value, label in field.choices],
                }
            )
        if isinstance(field, models.BooleanField):
            return JsonResponse(
                {
                    "kind": "choice",
                    "choices": [["True", _("True")], ["False", _("False")]],
                }
            )
        if isinstance(field, models.DateTimeField):
            return JsonResponse({"kind": "datetime"})
        if isinstance(field, models.DateField):
            return JsonResponse({"kind": "date"})
        if isinstance(
            field, (models.IntegerField, models.DecimalField, models.FloatField)
        ):
            return JsonResponse({"kind": "number"})
        return JsonResponse({"kind": "text"})

    def _render_field_select(self, request):
        """Return the field-name <select> HTML for one field_mapping/filters row (used when the Target Model changes)."""
        builder = request.GET.get("builder", "field_mapping")
        row_id = request.GET.get("row_id", "0")
        content_type_id = request.GET.get("content_type")
        selected_field = request.GET.get("selected_field", "")

        model_cls = self._resolve_model(content_type_id)
        choices = self._field_choices(model_cls) if model_cls else []
        return HttpResponse(
            render_to_string(
                "whatsapp_bot_rule/partials/kv_field_select.html",
                {
                    "builder": builder,
                    "row_id": row_id,
                    "field_choices": choices,
                    "field_name": selected_field,
                },
                request=request,
            )
        )

    def _render_value_widget_response(self, request):
        builder = request.GET.get("builder", "field_mapping")
        row_id = request.GET.get("row_id", "0")
        content_type_id = request.GET.get("content_type")
        field_name = request.GET.get(f"{builder}_key_{row_id}") or request.GET.get(
            "field_name"
        )
        existing_value = request.GET.get("existing_value", "")

        model_cls = self._resolve_model(content_type_id)
        html = self._render_value_widget(
            model_cls, field_name, builder, row_id, existing_value
        )
        return HttpResponse(html)

    def _value_widget_name_id(self, builder, row_id):
        name = f"{builder}_value_{row_id}"
        return name, f"id_{name}"

    def _render_value_widget(
        self, model_cls, field_name, builder, row_id, existing_value=""
    ):
        """Return the value-widget HTML for one field_mapping/filters row."""
        if not model_cls or not field_name:
            return self._render_text_widget(builder, row_id, existing_value)

        # A value containing a {{token}} isn't a valid stored choice/FK id -
        # always fall back to plain text so the token stays visible and
        # editable instead of being silently dropped by a select widget.
        if existing_value and "{{" in existing_value:
            return self._render_text_widget(builder, row_id, existing_value)

        try:
            field = model_cls._meta.get_field(field_name)
        except Exception:
            return self._render_text_widget(builder, row_id, existing_value)

        if isinstance(field, (models.ForeignKey, models.ManyToManyField)):
            return self._render_fk_widget(field, builder, row_id, existing_value)
        if getattr(field, "choices", None):
            return self._render_choice_widget(
                [(v, str(l)) for v, l in field.choices], builder, row_id, existing_value
            )
        if isinstance(field, models.BooleanField):
            return self._render_choice_widget(
                [("True", _("True")), ("False", _("False"))],
                builder,
                row_id,
                existing_value,
            )
        if isinstance(field, models.DateTimeField):
            return self._render_typed_widget(
                "datetime-local", builder, row_id, existing_value
            )
        if isinstance(field, models.DateField):
            return self._render_typed_widget("date", builder, row_id, existing_value)
        if isinstance(
            field, (models.IntegerField, models.DecimalField, models.FloatField)
        ):
            return self._render_typed_widget("number", builder, row_id, existing_value)
        return self._render_text_widget(builder, row_id, existing_value)

    def _render_text_widget(self, builder, row_id, existing_value=""):
        name, field_id = self._value_widget_name_id(builder, row_id)
        return format_html(
            '<input type="text" name="{}" id="{}" value="{}" placeholder="{}" '
            'class="kv-value-live w-full text-sm border border-dark-50 rounded-md p-2 font-mono">',
            name,
            field_id,
            existing_value,
            "{{variables.name}}",
        )

    def _render_typed_widget(self, input_type, builder, row_id, existing_value=""):
        name, field_id = self._value_widget_name_id(builder, row_id)
        return format_html(
            '<input type="{}" name="{}" id="{}" value="{}" '
            'class="kv-value-live w-full text-sm border border-dark-50 rounded-md p-2">',
            input_type,
            name,
            field_id,
            existing_value,
        )

    def _render_choice_widget(self, choices, builder, row_id, existing_value=""):
        name, field_id = self._value_widget_name_id(builder, row_id)
        options_html = mark_safe('<option value="">---------</option>')
        for value, label in choices:
            options_html += format_html(
                '<option value="{}" {}>{}</option>',
                value,
                "selected" if str(value) == str(existing_value) else "",
                label,
            )
        return format_html(
            '<select name="{}" id="{}" class="kv-value-live js-example-basic-single headselect w-full text-sm">{}</select>',
            name,
            field_id,
            options_html,
        )

    def _render_fk_widget(self, field, builder, row_id, existing_value=""):
        """
        Real select2-pagination FK widget (AJAX search), not a dump-all-rows
        <select> - Lead Owner/Assigned To etc. need search over large tables.
        """
        name, field_id = self._value_widget_name_id(builder, row_id)
        related_model = field.related_model
        select2_url = reverse_lazy(
            "generics:model_select2",
            kwargs={
                "app_label": related_model._meta.app_label,
                "model_name": related_model._meta.model_name,
            },
        )
        selected_option = ""
        if existing_value:
            related_obj = related_model.objects.filter(pk=existing_value).first()
            if related_obj:
                selected_option = format_html(
                    '<option value="{}" selected>{}</option>',
                    existing_value,
                    related_obj,
                )
        return format_html(
            '<select name="{}" id="{}" class="kv-value-live select2-pagination w-full text-sm" '
            'data-url="{}" data-placeholder="{}" data-field-name="{}">{}</select>',
            name,
            field_id,
            select2_url,
            _("Select a record"),
            name,
            selected_option,
        )


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied(["whatsapp.change_whatsappbotrule"]),
    name="dispatch",
)
class WhatsAppKeyValueAddRowView(LoginRequiredMixin, View):
    """Return one new blank field_mapping/filters row, appended via hx-swap=beforeend."""

    def get(self, request, *args, **kwargs):
        builder = request.GET.get("builder", "field_mapping")
        row_id = self._next_row_id(request, builder)
        content_type_id = request.GET.get("content_type", "")
        options_view = WhatsAppFieldMappingOptionsView()
        model_cls = (
            options_view._resolve_model(content_type_id) if content_type_id else None
        )
        field_choices = options_view._field_choices(model_cls) if model_cls else []
        html = render_to_string(
            "whatsapp_bot_rule/partials/kv_row.html",
            {
                "builder": builder,
                "row_id": row_id,
                "field_name": "",
                "value": "",
                "field_choices": field_choices,
            },
            request=request,
        )
        return HttpResponse(html)

    def _next_row_id(self, request, builder):
        """Return max row id currently present in the included form data, + 1."""
        prefix = f"{builder}_key_"
        max_id = -1
        for key in request.GET:
            if key.startswith(prefix):
                suffix = key[len(prefix) :]
                if suffix.isdigit():
                    max_id = max(max_id, int(suffix))
        return str(max_id + 1)


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied(["whatsapp.change_whatsappbotrule"]),
    name="dispatch",
)
class WhatsAppKeyValueRemoveRowView(LoginRequiredMixin, View):
    """Remove a field_mapping/filters row - client's hx-swap=outerHTML on the row does the work."""

    def delete(self, request, row_id, *args, **kwargs):
        return HttpResponse("")


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied(["whatsapp.change_whatsappbotrule"]),
    name="dispatch",
)
class WhatsAppOptionsAddRowView(LoginRequiredMixin, View):
    """Return one new blank button/list option row, appended via hx-swap=beforeend."""

    def get(self, request, *args, **kwargs):
        max_id = -1
        for key in request.GET:
            if key.startswith("options_id_"):
                suffix = key[len("options_id_") :]
                if suffix.isdigit():
                    max_id = max(max_id, int(suffix))
        row_id = str(max_id + 1)
        html = render_to_string(
            "whatsapp_bot_rule/partials/options_row.html",
            {"row_id": row_id, "option_id": "", "label": ""},
            request=request,
        )
        return HttpResponse(html)


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied(["whatsapp.change_whatsappbotrule"]),
    name="dispatch",
)
class WhatsAppOptionsRemoveRowView(LoginRequiredMixin, View):
    """Remove an option row - client's hx-swap=outerHTML on the row does the work."""

    def delete(self, request, row_id, *args, **kwargs):
        return HttpResponse("")


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied(["whatsapp.change_whatsappbotrule"]),
    name="dispatch",
)
class WhatsAppBranchAddRowView(LoginRequiredMixin, View):
    """Return one new blank condition branch, appended via hx-swap=beforeend."""

    def get(self, request, *args, **kwargs):
        from ..forms import RULE_TYPES

        max_id = -1
        for key in request.GET:
            if key.startswith("branches_handle_"):
                suffix = key[len("branches_handle_") :]
                if suffix.isdigit():
                    max_id = max(max_id, int(suffix))
        branch_id = str(max_id + 1)
        html = render_to_string(
            "whatsapp_bot_rule/partials/branch_row.html",
            {
                "branch_id": branch_id,
                "handle": "",
                "rules": [{"row_id": "0", "type": "", "field": "", "value": ""}],
                "rule_types": RULE_TYPES,
            },
            request=request,
        )
        return HttpResponse(html)


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied(["whatsapp.change_whatsappbotrule"]),
    name="dispatch",
)
class WhatsAppBranchRemoveRowView(LoginRequiredMixin, View):
    """Remove a condition branch - client's hx-swap=outerHTML on the row does the work."""

    def delete(self, request, row_id, *args, **kwargs):
        return HttpResponse("")


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied(["whatsapp.change_whatsappbotrule"]),
    name="dispatch",
)
class WhatsAppRuleAddRowView(LoginRequiredMixin, View):
    """Return one new blank rule row within a branch, appended via hx-swap=beforeend."""

    def get(self, request, *args, **kwargs):
        from ..forms import RULE_TYPES

        branch_id = request.GET.get("branch_id", "0")
        prefix = f"branches_rule_type_{branch_id}_"
        max_id = -1
        for key in request.GET:
            if key.startswith(prefix):
                suffix = key[len(prefix) :]
                if suffix.isdigit():
                    max_id = max(max_id, int(suffix))
        row_id = str(max_id + 1)
        html = render_to_string(
            "whatsapp_bot_rule/partials/rule_row.html",
            {
                "branch_id": branch_id,
                "row_id": row_id,
                "type": "",
                "field": "",
                "value": "",
                "rule_types": RULE_TYPES,
            },
            request=request,
        )
        return HttpResponse(html)


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied(["whatsapp.change_whatsappbotrule"]),
    name="dispatch",
)
class WhatsAppRuleRemoveRowView(LoginRequiredMixin, View):
    """Remove a rule row - client's hx-swap=outerHTML on the row does the work."""

    def delete(self, request, branch_id, row_id, *args, **kwargs):
        return HttpResponse("")


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied("whatsapp.change_whatsappbotrule", modal=True),
    name="dispatch",
)
class WhatsAppBotRuleNodeDeleteView(LoginRequiredMixin, HorillaSingleDeleteView):
    """Delete view for a Bot Rule node."""

    model = WhatsAppBotRuleNode

    def get_post_delete_response(self):
        """Return HTMX script to reload the builder after successful delete."""
        return HttpResponse("<script>$('#reloadButton').click();</script>")


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied(["whatsapp.change_whatsappbotrule"]),
    name="dispatch",
)
class WhatsAppBotRuleEdgeFormView(LoginRequiredMixin, HorillaSingleFormView):
    """Create and update form view for a single Bot Rule edge."""

    model = WhatsAppBotRuleEdge
    form_class = WhatsAppBotRuleEdgeForm
    form_title = _("Flow Edge")
    modal_height = False

    @cached_property
    def flow(self):
        """Return the parent flow, from the edge (update) or the query string (create)."""
        pk = self.kwargs.get("pk")
        if pk:
            return get_object_or_404(WhatsAppBotRuleEdge, pk=pk).flow
        return get_object_or_404(WhatsAppBotRule, pk=self.request.GET.get("flow"))

    @cached_property
    def form_url(self):
        """
        Return the create or update URL for the edge form. The `?flow=`
        query string is appended automatically by HorillaSingleFormView from
        request.GET, so it must NOT be added again here.
        """
        pk = self.kwargs.get("pk")
        if pk:
            return reverse_lazy(
                "whatsapp:whatsapp_bot_rule_edge_update_view", kwargs={"pk": pk}
            )
        return reverse_lazy("whatsapp:whatsapp_bot_rule_edge_create_view")

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["flow"] = self.flow
        source_node_id = self.request.GET.get("source_node")
        if source_node_id and not self.kwargs.get("pk"):
            kwargs["initial"] = {
                **kwargs.get("initial", {}),
                "source_node": source_node_id,
            }
            kwargs["source_node"] = self.flow.nodes.filter(pk=source_node_id).first()
        return kwargs

    def form_valid(self, form):
        form.instance.flow = self.flow
        return super().form_valid(form)


@method_decorator(htmx_required, name="dispatch")
@method_decorator(
    permission_required_or_denied("whatsapp.change_whatsappbotrule", modal=True),
    name="dispatch",
)
class WhatsAppBotRuleEdgeDeleteView(LoginRequiredMixin, HorillaSingleDeleteView):
    """Delete view for a Bot Rule edge."""

    model = WhatsAppBotRuleEdge

    def get_post_delete_response(self):
        """Return HTMX script to reload the builder after successful delete."""
        return HttpResponse("<script>$('#reloadButton').click();</script>")
