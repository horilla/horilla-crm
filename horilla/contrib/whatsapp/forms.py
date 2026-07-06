"""
Forms for the whatsapp app
"""

# Third-party imports (Django)
from django import forms
from django.db import transaction

from horilla.contrib.core.models import HorillaContentType
from horilla.contrib.generics.forms import HorillaModelForm, PasswordInputWithEye
from horilla.contrib.utils.middlewares import _thread_local

# First party imports (Horilla)
from horilla.db.models import Q
from horilla.urls import reverse
from horilla.utils.translation import gettext_lazy as _

# Local imports
from .models import (
    WhatsAppAccount,
    WhatsAppBotRule,
    WhatsAppBotRuleEdge,
    WhatsAppBotRuleNode,
    WhatsAppFlow,
    WhatsAppTemplate,
)
from .services import WhatsAppAPIError, WhatsAppCloudAPIClient


def _active_company():
    """Return the current request's active company, if any."""
    request = getattr(_thread_local, "request", None)
    return getattr(request, "active_company", None)


class WhatsAppAccountForm(HorillaModelForm):
    """
    Form for connecting/updating a WhatsApp Business (Cloud API) account.

    access_token/webhook_verify_token are always rendered blank; the value is
    only overwritten when the field is resubmitted with a new value, since the
    stored value is encrypted and never decrypted back into a form field.
    """

    access_token = forms.CharField(
        widget=PasswordInputWithEye(attrs={"placeholder": _("Enter access token")}),
        help_text=_("Permanent access token generated from the Meta app."),
        required=False,
    )
    webhook_verify_token = forms.CharField(
        widget=PasswordInputWithEye(
            attrs={"placeholder": _("Enter webhook verify token")}
        ),
        required=False,
    )

    class Meta:
        """Meta class for WhatsAppAccountForm."""

        model = WhatsAppAccount
        fields = "__all__"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not self.instance.pk:
            self.fields["access_token"].required = True

        default_bot_rule_qs = WhatsAppBotRule.objects.filter(
            trigger_type="inbound_message", content_type__isnull=True
        )
        if self.instance.pk:
            default_bot_rule_qs = default_bot_rule_qs.filter(account=self.instance)
        else:
            # No account exists yet to scope by, so offer every inbound-message
            # rule for the active company instead of an empty queryset.
            company = _active_company()
            if company:
                default_bot_rule_qs = default_bot_rule_qs.filter(company=company)
        self.fields["default_bot_rule"].queryset = default_bot_rule_qs

    def clean_access_token(self):
        """Keep the existing encrypted token when the field is left blank."""
        value = self.cleaned_data.get("access_token")
        if not value and self.instance.pk:
            return self.instance.access_token
        return value

    def clean_webhook_verify_token(self):
        """Keep the existing encrypted token when the field is left blank."""
        value = self.cleaned_data.get("webhook_verify_token")
        if not value and self.instance.pk:
            return self.instance.webhook_verify_token
        return value


class WhatsAppTemplateForm(HorillaModelForm):
    """Form for creating/updating a WhatsApp message template."""

    field_order = ["account", "title", "name", "content_type"]

    class Meta:
        """Meta class for WhatsAppTemplateForm."""

        model = WhatsAppTemplate
        fields = "__all__"

    def __init__(self, *args, request=None, **kwargs):
        super().__init__(*args, request=request, **kwargs)
        self.fields["content_type"].empty_label = _("General (any model)")
        company = self.instance.company_id and self.instance.company
        if not company:
            company = _active_company()
        if not company:
            from horilla.contrib.core.models import Company

            company = Company.objects.order_by("pk").first()

        accounts = WhatsAppAccount.objects.filter(
            company=company, is_active=True
        ).order_by("-is_primary", "pk")
        self.fields["account"].queryset = accounts
        self.fields["account"].required = True
        self.fields["account"].empty_label = None

        # Which account's templates to list: the one just picked (reload on
        # change, or the submitted value), else the template's own, else the
        # company's primary account.
        picked = (
            self.data.get("account")
            or (request.GET.get("account") if request is not None else None)
            or self.instance.account_id
        )
        account = accounts.filter(pk=picked).first() if picked else None
        account = account or accounts.first()
        if account:
            self.initial["account"] = account.pk
            self.fields["account"].initial = account.pk
        reload_url = (
            reverse(
                "whatsapp:whatsapp_template_update_view",
                kwargs={"pk": self.instance.pk},
            )
            if self.instance.pk
            else reverse("whatsapp:whatsapp_template_create_view")
        )
        self.fields["account"].widget.attrs.update(
            {
                "hx-get": reload_url,
                "hx-trigger": "change",
                "hx-target": "#modalBox",
                "hx-swap": "innerHTML",
                "hx-include": "[name='title'],[name='account']",
            }
        )

        choices = [("", _("Select a template"))]
        if account and account.business_account_id:
            client = WhatsAppCloudAPIClient(account)
            try:
                templates = client.list_templates(account.business_account_id)
            except WhatsAppAPIError:
                templates = []
            for template in templates:
                value = f"{template['name']}|{template['language']}"
                label = f"{template['name']} ({template['language']})"
                choices.append((value, label))

        current_value = (
            f"{self.instance.name}|{self.instance.language}" if self.instance.pk else ""
        )
        if self.instance.pk and current_value not in dict(choices):
            choices.append(
                (current_value, f"{self.instance.name} ({self.instance.language})")
            )

        self.fields["name"] = forms.ChoiceField(
            choices=choices,
            label=self.fields["name"].label,
            required=True,
            widget=forms.Select(
                attrs={
                    "class": "js-example-basic-single headselect w-full text-sm",
                    "data-placeholder": _("Select a template"),
                }
            ),
        )
        if self.instance.pk:
            self.initial["name"] = current_value
        self.fields["language"].widget = forms.HiddenInput()
        self.fields["language"].required = False
        self.fields["category"].widget = forms.HiddenInput()
        self.fields["category"].required = False
        self._add_variable_fields(request, account, current_value, reload_url)

    def _template_variable_count(self, selected, account):
        """How many {{n}} variables the chosen template's text has (0 when unknown)."""
        if not selected:
            return 0
        name, _sep, language = selected.partition("|")
        if (
            self.instance.pk
            and self.instance.components
            and name == self.instance.name
            and language == self.instance.language
        ):
            components = self.instance.components
        else:
            if not account or not account.business_account_id:
                return 0
            try:
                remote = WhatsAppCloudAPIClient(account).fetch_template(
                    account.business_account_id, name, language
                )
            except WhatsAppAPIError:
                return 0
            components = (remote or {}).get("components", [])
        return WhatsAppTemplate._describe_body(components)["variables"]

    def _add_variable_fields(self, request, account, current_value, reload_url):
        """
        One dropdown per variable in the template's text, each listing the fields of
        the template's Related Model, saved into ``variable_fields`` (used when an
        automation sends the template). The form reloads when the template or the
        Related Model changes, so the dropdowns match them.
        """
        from django.apps import apps as django_apps

        from .delivery import split_variable_fields, variable_field_choices

        get = request.GET if request is not None else {}
        # A reload (from the template / Related Model selectors) carries the values.
        for key in ("title", "content_type"):
            if get.get(key):
                self.initial[key] = get.get(key)
        selected = self.data.get("name") or get.get("name") or current_value
        if get.get("name"):
            self.initial["name"] = get.get("name")

        include = "[name='account'],[name='title'],[name='name'],[name='content_type']"
        reload_attrs = {
            "hx-get": reload_url,
            "hx-trigger": "change",
            "hx-target": "#modalBox",
            "hx-swap": "innerHTML",
            "hx-include": include,
        }
        self.fields["name"].widget.attrs.update(reload_attrs)
        self.fields["content_type"].widget.attrs.update(reload_attrs)

        if "variable_fields" in self.fields:
            self.fields["variable_fields"].required = False
            self.fields["variable_fields"].widget = forms.HiddenInput()

        content_type_id = (
            self.data.get("content_type")
            or get.get("content_type")
            or self.instance.content_type_id
        )
        model = None
        if str(content_type_id or "").isdigit():
            content_type = HorillaContentType.objects.filter(pk=content_type_id).first()
            model = content_type.model_class() if content_type else None
        choices = [("", "---------")] + [
            (value, str(label)) for value, label in variable_field_choices(model)
        ]

        count = self._template_variable_count(selected, account)
        saved = split_variable_fields(self.instance.variable_fields)
        names = []
        for index in range(1, count + 1):
            name = f"variable_{index}"
            self.fields[name] = forms.ChoiceField(
                choices=choices,
                required=False,
                label=_("Variable %(n)s") % {"n": index},
                initial=saved[index - 1] if index <= len(saved) else "",
                widget=forms.Select(
                    attrs={"class": "js-example-basic-single headselect w-full text-sm"}
                ),
                help_text=(
                    _("The record field that fills {{%(n)s}}.") % {"n": index}
                    if index == 1
                    else ""
                ),
            )
            names.append(name)
        self._variable_field_names = names
        self.order_fields(["account", "title", "name", "content_type"] + names)

    def clean(self):
        cleaned_data = super().clean()
        # The chosen record fields, in order, saved on the template.
        cleaned_data["variable_fields"] = ",".join(
            cleaned_data.get(name) or ""
            for name in getattr(self, "_variable_field_names", [])
        )
        selected = cleaned_data.get("name")
        company = (self.instance.company_id and self.instance.company) or (
            _active_company()
        )
        if not (selected and company):
            return cleaned_data

        name, _sep, language = selected.partition("|")
        cleaned_data["name"] = name
        cleaned_data["language"] = language

        account = cleaned_data.get("account") or (
            WhatsAppAccount.objects.filter(company=company, is_active=True)
            .order_by("-is_primary")
            .first()
        )
        if not account or not account.business_account_id:
            self.add_error(
                "name",
                _(
                    "The selected WhatsApp account has no Business Account ID, "
                    "so the template body can't be fetched from Meta."
                ),
            )
            return cleaned_data

        client = WhatsAppCloudAPIClient(account)
        try:
            template = client.fetch_template(
                account.business_account_id, name, language
            )
        except WhatsAppAPIError as exc:
            self.add_error("name", _("Could not fetch template from Meta: %s") % exc)
            return cleaned_data

        if not template:
            self.add_error(
                "name",
                _(
                    "No approved template named '%(name)s' in '%(language)s' "
                    "was found in Meta Business Manager."
                )
                % {"name": name, "language": language},
            )
            return cleaned_data

        components = template.get("components", [])
        cleaned_data["components"] = components
        cleaned_data["sample_body"] = WhatsAppTemplate._describe_body(components)[
            "text"
        ]
        cleaned_data["category"] = (template.get("category") or "").lower()
        return cleaned_data

    def _post_clean(self):
        if self.cleaned_data.get("language"):
            self.instance.language = self.cleaned_data["language"]
        if self.cleaned_data.get("category"):
            self.instance.category = self.cleaned_data["category"]
        super()._post_clean()


class WhatsAppFlowForm(HorillaModelForm):
    """Form for creating/updating a WhatsApp Flow reference."""

    class Meta:
        """Meta class for WhatsAppFlowForm."""

        model = WhatsAppFlow
        fields = "__all__"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["content_type"].empty_label = _("General (any model)")
        company = self.instance.company_id and self.instance.company
        if not company:
            company = _active_company()
        if not company:
            from horilla.contrib.core.models import Company

            company = Company.objects.order_by("pk").first()

        choices = [("", _("Select a WhatsApp Flow"))]
        account = (
            WhatsAppAccount.objects.filter(company=company, is_active=True)
            .order_by("-is_primary")
            .first()
            if company
            else None
        )
        if account and account.business_account_id:
            client = WhatsAppCloudAPIClient(account)
            try:
                flows = client.list_flows(account.business_account_id)
            except WhatsAppAPIError:
                flows = []
            for flow in flows:
                value = f"{flow['id']}|{flow.get('name', '')}"
                label = flow.get("name") or flow["id"]
                choices.append((value, label))

        current_value = (
            f"{self.instance.flow_id}|{self.instance.flow_name or ''}"
            if self.instance.pk
            else ""
        )
        if self.instance.pk and current_value not in dict(choices):
            choices.append(
                (current_value, self.instance.flow_name or self.instance.flow_id)
            )

        self.fields["flow_id"] = forms.ChoiceField(
            choices=choices,
            label=_("Flow"),
            required=True,
            widget=forms.Select(
                attrs={
                    "class": "js-example-basic-single headselect w-full text-sm",
                    "data-placeholder": _("Select a WhatsApp Flow"),
                }
            ),
        )
        if self.instance.pk:
            self.initial["flow_id"] = current_value
        self.fields["flow_name"].widget = forms.HiddenInput()
        self.fields["flow_name"].required = False

    def clean(self):
        cleaned_data = super().clean()
        selected = cleaned_data.get("flow_id")
        if not selected:
            return cleaned_data

        flow_id, _sep, flow_name = selected.partition("|")
        cleaned_data["flow_id"] = flow_id
        cleaned_data["flow_name"] = flow_name
        return cleaned_data

    def _post_clean(self):
        if self.cleaned_data.get("flow_name"):
            self.instance.flow_name = self.cleaned_data["flow_name"]
        super()._post_clean()


class WhatsAppSendMessageForm(forms.Form):
    """Form for sending a message from the conversation panel."""

    body = forms.CharField(required=False, widget=forms.Textarea)
    attachment = forms.FileField(required=False)

    def clean(self):
        cleaned_data = super().clean()
        if not cleaned_data.get("body") and not cleaned_data.get("attachment"):
            raise forms.ValidationError(
                _("Enter a message or attach a file before sending.")
            )
        return cleaned_data


class WhatsAppBotRuleForm(HorillaModelForm):
    """Form for creating/updating a Bot Rule's top-level settings."""

    field_order = [
        "name",
        "account",
        "content_type",
        "trigger_type",
        "trigger_keywords",
        "is_active",
        "retrigger_cooldown_value",
        "retrigger_cooldown_unit",
        "description",
    ]

    class Meta:
        """Meta class for WhatsAppBotRuleForm."""

        model = WhatsAppBotRule
        fields = "__all__"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["content_type"].empty_label = _("General (any model)")

    def clean(self):
        cleaned_data = super().clean()
        trigger_type = cleaned_data.get("trigger_type")
        trigger_keywords = cleaned_data.get("trigger_keywords")
        account = cleaned_data.get("account")
        content_type = cleaned_data.get("content_type")

        if trigger_type == "keyword" and not trigger_keywords:
            self.add_error(
                "trigger_keywords",
                _("Trigger Keywords are required when Trigger Type is Keyword."),
            )
        elif trigger_type == "keyword" and account:
            keywords = {
                keyword.strip().lower()
                for keyword in trigger_keywords.split(",")
                if keyword.strip()
            }
            # A General rule (content_type=None) matches every conversation,
            # so it can conflict with both other General rules and
            # model-specific ones; a model-specific rule only conflicts with
            # rules for that same model or General ones.
            other_rules = WhatsAppBotRule.objects.filter(
                account=account, trigger_type="keyword", is_active=True
            )
            if content_type:
                other_rules = other_rules.filter(
                    Q(content_type=content_type) | Q(content_type__isnull=True)
                )
            if self.instance.pk:
                other_rules = other_rules.exclude(pk=self.instance.pk)
            for other_rule in other_rules:
                other_keywords = {
                    keyword.strip().lower()
                    for keyword in (other_rule.trigger_keywords or "").split(",")
                    if keyword.strip()
                }
                overlap = keywords & other_keywords
                if overlap:
                    self.add_error(
                        "trigger_keywords",
                        _(
                            "Keyword(s) %(keywords)s already trigger another "
                            'active flow ("%(flow_name)s") on this account '
                            "for this model."
                        )
                        % {
                            "keywords": ", ".join(sorted(overlap)),
                            "flow_name": other_rule.name,
                        },
                    )
                    break
        elif trigger_type == "inbound_message" and account:
            other_rules = WhatsAppBotRule.objects.filter(
                account=account, trigger_type="inbound_message", is_active=True
            )
            if content_type:
                other_rules = other_rules.filter(
                    Q(content_type=content_type) | Q(content_type__isnull=True)
                )
            if self.instance.pk:
                other_rules = other_rules.exclude(pk=self.instance.pk)
            other_rule = other_rules.first()
            if other_rule:
                self.add_error(
                    "trigger_type",
                    _(
                        'Another active flow ("%(flow_name)s") already uses '
                        "Inbound Message as its trigger for this account and "
                        "model. Only one active Inbound Message flow is "
                        "allowed per account/model combination."
                    )
                    % {"flow_name": other_rule.name},
                )

        return cleaned_data


#: Condition-branch rule types, and which parts of a rule row apply to each -
#: shared between the rule-row partial (which fields to render) and
#: WhatsAppBotRuleNodeForm._parse_branches_field (which POST keys to read).
RULE_TYPES = [
    ("field_equals", _("Field equals")),
    ("field_not_equals", _("Field not equals")),
    ("field_contains", _("Field contains")),
    ("field_gt", _("Field greater than")),
    ("field_lt", _("Field less than")),
    ("date_before", _("Date before")),
    ("date_after", _("Date after")),
    ("record_exists", _("Linked record exists")),
    ("record_not_exists", _("Linked record does not exist")),
    ("variable_exists", _("Variable is set")),
    ("button_selected", _("Button/list option selected")),
]
RULE_TYPES_WITH_FIELD = [
    "field_equals",
    "field_not_equals",
    "field_contains",
    "field_gt",
    "field_lt",
    "date_before",
    "date_after",
]
RULE_TYPES_WITH_VALUE = RULE_TYPES_WITH_FIELD + ["button_selected"]
RULE_TYPES_WITH_VARIABLE = ["variable_exists"]

#: Which node-type-specific field names should be visible for each node_type.
#: Drives the show/hide JS in whatsapp_bot_rule_node_form.html - keep in sync
#: with the fields declared on WhatsAppBotRuleNodeForm below.
NODE_TYPE_FIELD_GROUPS = {
    "message": ["body"],
    "question": ["prompt", "variable_name"],
    "buttons": ["body", "options", "variable_name"],
    "list": ["body", "options", "button_text", "variable_name"],
    "condition": ["branches", "default_handle"],
    "create_record": ["content_type", "field_mapping"],
    "update_record": ["content_type", "field_mapping"],
    "search_record": [
        "content_type",
        "filters",
        "found_branch_handle",
        "not_found_branch_handle",
    ],
    "assign_owner": [],
    "add_note": ["text"],
    "send_template": ["template"],
    "send_meta_flow": ["meta_flow", "variable_prefix"],
    "wait": ["duration_seconds"],
    "end": [],
}


class WhatsAppBotRuleNodeForm(HorillaModelForm):
    """
    Form for creating/updating a single Bot Rule node. Which fields are
    relevant depends on node_type (see NODE_TYPE_FIELD_GROUPS); all of them
    are always present on the form but only the ones for the selected
    node_type are shown (see whatsapp_bot_rule_node_form.html), and only
    those are merged into config on save.

    Simple scalar values (body, prompt, ...) get real typed fields.
    Structures with an unpredictable number of repeating rows (button/list
    options, condition branches, field mappings, filters) are backed by a
    hidden JSON CharField each, kept in sync by a repeatable-row builder UI
    in whatsapp_bot_rule_node_form.html - never hand-typed JSON.
    """

    body = forms.CharField(
        required=False,
        label=_("Message Body"),
        widget=forms.Textarea(attrs={"rows": 3}),
        help_text=_("Supports {{variables.name}} interpolation."),
    )
    prompt = forms.CharField(
        required=False,
        label=_("Question Prompt"),
        widget=forms.Textarea(attrs={"rows": 3}),
    )
    variable_name = forms.CharField(
        required=False,
        label=_("Save Reply As Variable"),
        help_text=_("Name to store the contact's reply under, e.g. full_name."),
    )
    button_text = forms.CharField(
        required=False,
        label=_("List Button Text"),
        help_text=_("Label shown on the button that opens the list."),
    )
    default_handle = forms.CharField(
        required=False,
        label=_("Default Branch Handle"),
        help_text=_("Used when no branch's rules match."),
    )
    found_branch_handle = forms.CharField(
        required=False,
        label=_("Found Branch Handle"),
        initial="found",
    )
    not_found_branch_handle = forms.CharField(
        required=False,
        label=_("Not Found Branch Handle"),
        initial="not_found",
    )
    text = forms.CharField(
        required=False,
        label=_("Note Text"),
        widget=forms.Textarea(attrs={"rows": 3}),
    )
    template = forms.ModelChoiceField(
        queryset=None,
        required=False,
        label=_("Template"),
        widget=forms.Select(
            attrs={
                "class": "js-example-basic-single headselect w-full text-sm",
                "data-placeholder": _("Select a template"),
            }
        ),
    )
    variable_prefix = forms.CharField(
        required=False,
        label=_("Answers Variable Prefix"),
        initial="meta_flow",
        help_text=_("Submitted answers are stored as <prefix>.<field>."),
    )
    duration_seconds = forms.IntegerField(
        required=False,
        min_value=0,
        label=_("Wait Duration (seconds)"),
    )
    content_type = forms.ModelChoiceField(
        queryset=None,
        required=False,
        label=_("Target Model"),
        help_text=_(
            "Used by Create/Search Record nodes: the model this node "
            "operates on. For Update Record, this only helps suggest field "
            "names below - the node always updates whatever record is "
            "actually linked at runtime."
        ),
        widget=forms.Select(
            attrs={
                "class": "js-example-basic-single headselect w-full text-sm",
                "data-placeholder": _("Select a model"),
            }
        ),
    )
    meta_flow = forms.ModelChoiceField(
        queryset=None,
        required=False,
        label=_("Meta WhatsApp Flow"),
        help_text=_("Used by Send Meta Flow nodes: the static Meta Flow to send."),
        widget=forms.Select(
            attrs={
                "class": "js-example-basic-single headselect w-full text-sm",
                "data-placeholder": _("Select a WhatsApp Flow"),
            }
        ),
    )

    class Meta:
        """Meta class for WhatsAppBotRuleNodeForm."""

        model = WhatsAppBotRuleNode
        fields = [
            "node_key",
            "node_type",
            "order",
            "is_start",
            "content_type",
            "meta_flow",
            "body",
            "prompt",
            "variable_name",
            "button_text",
            "default_handle",
            "found_branch_handle",
            "not_found_branch_handle",
            "text",
            "template",
            "variable_prefix",
            "duration_seconds",
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Snapshot the handle values this node produced BEFORE this edit, so
        # clean()/apply_handle_renames() can tell a rename ("found_branch_handle"
        # changed from "not_found" to "Not Found") apart from an unrelated
        # save that leaves handles untouched - existing WhatsAppBotRuleEdge
        # rows reference the old string and would otherwise silently stop
        # matching at runtime (see WhatsAppBotRuleNode.get_outgoing_edge).
        self._old_handles = (
            WhatsAppBotRuleNode._keyed_handles(
                self.instance.node_type, self.instance.config
            )
            if self.instance.pk
            else {}
        )

        from horilla.contrib.core.models import HorillaContentType
        from horilla.registry.limiters import limit_content_types

        self.fields["content_type"].queryset = HorillaContentType.objects.filter(
            limit_content_types("whatsapp_flow_action_models")()
        )
        self.fields["meta_flow"].queryset = WhatsAppFlow.objects.filter(is_active=True)
        self.fields["template"].queryset = WhatsAppTemplate.objects.filter(
            is_active=True
        )

        # HorillaModelForm.__init__ overwrites every widget's `class` attr
        # (see single_step.py), so the select2 class must be re-applied here.
        for field_name in ("content_type", "meta_flow", "template"):
            placeholder = self.fields[field_name].widget.attrs.get(
                "data-placeholder", ""
            )
            self.fields[field_name].widget.attrs.update(
                {
                    "class": "js-example-basic-single headselect w-full text-sm",
                    "data-placeholder": placeholder,
                }
            )

        config = self.instance.config or {}
        if config.get("content_type_id"):
            self.initial["content_type"] = config["content_type_id"]
        elif config.get("_ui_hint_content_type_id"):
            # update_record has no content_type_id in its runtime config (it
            # always acts on session.related_to), but the Target Model
            # picker is still saved under this key purely so the builder can
            # restore it and re-populate the field_mapping dropdown when the
            # node is reopened.
            self.initial["content_type"] = config["_ui_hint_content_type_id"]
        if config.get("flow_id"):
            self.initial["meta_flow"] = config["flow_id"]
        if config.get("template_id"):
            self.initial["template"] = config["template_id"]

        simple_keys = [
            "body",
            "prompt",
            "variable_name",
            "button_text",
            "default_handle",
            "found_branch_handle",
            "not_found_branch_handle",
            "text",
            "variable_prefix",
            "duration_seconds",
        ]
        for key in simple_keys:
            if key in config and key not in self.initial:
                self.initial[key] = config[key]

        # If this is a bound resubmission (e.g. redisplaying after a
        # validation error) and a field's key is missing from the actual
        # POST body entirely - not submitted as an empty string, just
        # absent - treat that as "this field wasn't part of what changed"
        # rather than "the admin cleared it": backfill it from the node's
        # current saved config so the redisplay doesn't look like the field
        # lost its value. Only fields not shown for the currently-submitted
        # node_type would ever be missing like this (the JS in
        # whatsapp_bot_rule_node_form.html only serializes the visible
        # group's fields - see NODE_TYPE_FIELD_GROUPS), so this only ever
        # affects fields the admin never had a chance to see or edit in
        # this submission.
        if self.is_bound:
            self.data = self.data.copy()
            for key in simple_keys:
                if key in config and key not in self.data:
                    self.data[key] = config[key]

        for field_name, attrs in (("node_type", {"data-node-type-select": "1"}),):
            self.fields[field_name].widget.attrs.update(attrs)

    def _parse_kv_field(self, prefix):
        """
        Reconstruct a field_mapping/filters dict from flat POST rows
        (`<prefix>_key_<row_id>` / `<prefix>_value_<row_id>`), rendered and
        submitted as real named inputs by the htmx row builder - no hidden
        JSON blob, so there's no client-side serialization step to race.
        """
        key_prefix = f"{prefix}_key_"
        result = {}
        for name in self.data:
            if not name.startswith(key_prefix):
                continue
            row_id = name[len(key_prefix) :]
            field_name = self.data.get(name, "").strip()
            value = self.data.get(f"{prefix}_value_{row_id}", "")
            if field_name and value != "":
                result[field_name] = value
        return result

    def _parse_options_field(self):
        """Reconstruct the options list from flat POST rows (`options_id_<n>` / `options_label_<n>`)."""
        id_prefix = "options_id_"
        result = []
        for name in self.data:
            if not name.startswith(id_prefix):
                continue
            row_id = name[len(id_prefix) :]
            option_id = self.data.get(name, "").strip()
            label = self.data.get(f"options_label_{row_id}", "").strip()
            if option_id or label:
                result.append({"id": option_id, "label": label})
        return result

    def _parse_branches_field(self):
        """Reconstruct the nested branches list from flat POST rows."""
        handle_prefix = "branches_handle_"
        branch_ids = sorted(
            {
                name[len(handle_prefix) :]
                for name in self.data
                if name.startswith(handle_prefix)
            },
            key=lambda row_id: int(row_id) if row_id.isdigit() else 0,
        )
        rule_type_prefix = "branches_rule_type_"
        rule_keys = [
            name[len(rule_type_prefix) :]
            for name in self.data
            if name.startswith(rule_type_prefix)
        ]

        result = []
        for branch_id in branch_ids:
            handle = self.data.get(f"branches_handle_{branch_id}", "").strip()
            rules = []
            branch_rule_ids = sorted(
                (
                    key.split("_", 1)[1]
                    for key in rule_keys
                    if key.startswith(f"{branch_id}_")
                ),
                key=lambda row_id: int(row_id) if row_id.isdigit() else 0,
            )
            for rule_id in branch_rule_ids:
                rule_type = self.data.get(
                    f"branches_rule_type_{branch_id}_{rule_id}", ""
                ).strip()
                field_or_variable = self.data.get(
                    f"branches_rule_field_{branch_id}_{rule_id}", ""
                ).strip()
                value = self.data.get(
                    f"branches_rule_value_{branch_id}_{rule_id}", ""
                ).strip()
                if not rule_type:
                    continue
                rule = {"type": rule_type}
                if field_or_variable and rule_type in RULE_TYPES_WITH_VARIABLE:
                    rule["variable"] = field_or_variable
                elif field_or_variable and rule_type in RULE_TYPES_WITH_FIELD:
                    rule["field"] = field_or_variable
                if value and rule_type in RULE_TYPES_WITH_VALUE:
                    rule["value"] = value
                rules.append(rule)
            if handle or rules:
                result.append({"handle": handle, "rules": rules})
        return result

    def _guard_is_start_unset(self, cleaned_data):
        """
        Refuse to silently clear is_start on the flow's current start node.

        A plain HTML checkbox is simply absent from POST when unchecked, so
        Django can't tell "the admin deliberately unchecked this" apart from
        "this particular submission never touched the field at all" - every
        other edit to this node (message text, config, ...) resubmits the
        whole form and would otherwise silently drop is_start to False,
        leaving the flow with no entry point (FlowEngine.start() has nothing
        to run). Promoting a *different* node to start already flips this
        one off naturally via its own edit, so this only needs to block the
        one dangerous case: this node IS the start node, and this save says
        it no longer is.
        """
        if not self.instance.pk or not self.instance.is_start:
            return
        if cleaned_data.get("is_start"):
            return
        # Nothing was actually lost - the save is blocked below - but leave
        # the checkbox showing checked on redisplay too. Otherwise a bound
        # form re-renders exactly what was submitted (unchecked), which
        # reads as "the checkbox failed to save" rather than "this node is
        # still safely the start node, fix your submission and try again."
        cleaned_data["is_start"] = True
        self.data = self.data.copy()
        self.data["is_start"] = "on"
        self.add_error(
            "is_start",
            _(
                "This is the flow's start node. Mark a different node as "
                "the start node instead of unchecking this one, or the flow "
                "will have no entry point."
            ),
        )

    def clean(self):
        cleaned_data = super().clean()
        self._guard_is_start_unset(cleaned_data)
        node_type = cleaned_data.get("node_type")
        relevant = set(NODE_TYPE_FIELD_GROUPS.get(node_type, []))
        config = {}

        def take(field_name, config_key=None):
            if field_name not in relevant:
                return
            value = cleaned_data.get(field_name)
            if value in (None, ""):
                return
            config[config_key or field_name] = value

        def take_kv(field_name):
            if field_name not in relevant:
                return
            value = self._parse_kv_field(field_name)
            if value:
                config[field_name] = value

        take("body")
        take("prompt")
        take("variable_name")
        if "options" in relevant:
            options = self._parse_options_field()
            if options:
                config["options"] = options
        take("button_text")
        if "branches" in relevant:
            branches = self._parse_branches_field()
            if branches:
                config["branches"] = branches
        take("default_handle")
        take_kv("field_mapping")
        take_kv("filters")
        take("found_branch_handle")
        take("not_found_branch_handle")
        take("text")
        take("variable_prefix")
        take("duration_seconds")

        if "content_type" in relevant:
            content_type = cleaned_data.get("content_type")
            if node_type == "update_record":
                # Target Model is a builder-UI hint only here (drives the
                # field_mapping field-name dropdown) - update_record always
                # acts on whatever session.related_to is at runtime, so this
                # is optional and saved under a distinct "_ui_hint_" key the
                # engine never reads, purely so the builder can restore the
                # picker's selection when the node is reopened.
                if content_type:
                    config["_ui_hint_content_type_id"] = content_type.pk
            elif not content_type:
                self.add_error(
                    "content_type",
                    _("Target Model is required for this node type."),
                )
            else:
                config["content_type_id"] = content_type.pk

        if "meta_flow" in relevant:
            meta_flow = cleaned_data.get("meta_flow")
            if not meta_flow:
                self.add_error(
                    "meta_flow",
                    _("Meta WhatsApp Flow is required for this node type."),
                )
            else:
                config["flow_id"] = meta_flow.pk

        if "template" in relevant:
            template = cleaned_data.get("template")
            if not template:
                self.add_error(
                    "template", _("Template is required for this node type.")
                )
            else:
                config["template_id"] = template.pk

        cleaned_data["config"] = config
        self._validate_handle_renames(node_type, config)
        return cleaned_data

    def _validate_handle_renames(self, node_type, new_config):
        """
        Compute old-handle -> new-handle renames (keyed by role/position, so
        e.g. found_branch_handle and not_found_branch_handle changing
        together are paired correctly rather than ambiguously - an unordered
        set diff of old vs. new values alone can't tell which old handle
        became which new one) and refuse the save if two of this node's own
        handles would end up equal - WhatsAppBotRuleEdge.unique_together=
        (source_node, source_handle) would otherwise raise an IntegrityError
        on save instead of a clean form error.
        """
        new_handles = WhatsAppBotRuleNode._keyed_handles(node_type, new_config)
        renames = {
            old: new_handles[key]
            for key, old in self._old_handles.items()
            if key in new_handles and new_handles[key] != old
        }
        self._pending_handle_renames = renames

        # A handle disappearing entirely (its key existed before, produces
        # no handle now - e.g. found_branch_handle cleared to "") is a
        # removal, not a rename: nothing in `renames` catches it, since
        # there's no new value to pair it with. Block it if an edge still
        # depends on that exact handle - otherwise the edge silently stops
        # matching anything at runtime (WhatsAppBotRuleNode.get_outgoing_edge),
        # the same class of breakage as the is_start checkbox bug: a save
        # that never intended to touch this handle (e.g. it just wasn't
        # part of what the browser submitted) ends up erasing it anyway.
        if self.instance.pk:
            removed_handles = {
                old for key, old in self._old_handles.items() if key not in new_handles
            }
            in_use = set(
                self.instance.outgoing_edges.filter(
                    source_handle__in=removed_handles
                ).values_list("source_handle", flat=True)
            )
            for handle in in_use:
                self.add_error(
                    None,
                    _(
                        "Branch handle '%(handle)s' is still used by an "
                        "existing connection from this node. Update or "
                        "remove that connection first, or restore this "
                        "handle."
                    )
                    % {"handle": handle},
                )

        if not renames:
            return

        seen = set()
        duplicates = set()
        for handle in new_handles.values():
            if handle in seen:
                duplicates.add(handle)
            seen.add(handle)
        for handle in duplicates:
            self.add_error(
                None,
                _(
                    "Branch handle '%(handle)s' is used more than once on "
                    "this node - handles must be unique so connected edges "
                    "know which branch they belong to."
                )
                % {"handle": handle},
            )

    def _post_clean(self):
        self.instance.config = self.cleaned_data.get("config", {})
        super()._post_clean()

    def apply_handle_renames(self):
        """
        Update existing WhatsAppBotRuleEdge rows so a renamed handle
        (e.g. found_branch_handle edited from "not_found" to "Not Found")
        keeps its edges connected instead of silently orphaning them. Call
        after the node itself has been saved (needs self.instance.pk).
        """
        renames = getattr(self, "_pending_handle_renames", None)
        if not renames or not self.instance.pk:
            return

        with transaction.atomic():
            # Two-phase rename (old -> unique temp value -> new) so a
            # "rotation" (branch A: x->y, branch B: y->x, both changing in
            # the same save) can't transiently collide with the
            # (source_node, source_handle) unique constraint depending on
            # update order.
            temp_map = {}
            for index, old_handle in enumerate(renames):
                temp_handle = f"__renaming__{self.instance.pk}__{index}"
                updated = WhatsAppBotRuleEdge.objects.filter(
                    source_node=self.instance, source_handle=old_handle
                ).update(source_handle=temp_handle)
                if updated:
                    temp_map[temp_handle] = renames[old_handle]

            for temp_handle, new_handle in temp_map.items():
                WhatsAppBotRuleEdge.objects.filter(
                    source_node=self.instance, source_handle=temp_handle
                ).update(source_handle=new_handle)


class WhatsAppBotRuleEdgeForm(HorillaModelForm):
    """Form for connecting two Bot Rule nodes."""

    class Meta:
        """Meta class for WhatsAppBotRuleEdgeForm."""

        model = WhatsAppBotRuleEdge
        fields = ["source_node", "target_node", "source_handle"]

    def __init__(self, *args, flow=None, source_node=None, **kwargs):
        super().__init__(*args, **kwargs)
        request = getattr(self, "request", None)
        flow = (
            flow
            or getattr(self.instance, "flow", None)
            or (
                WhatsAppBotRule.objects.filter(pk=request.GET.get("flow")).first()
                if request
                else None
            )
        )
        if flow:
            self.fields["source_node"].queryset = flow.nodes.all()
            self.fields["target_node"].queryset = flow.nodes.all()
            for field_name in ("source_node", "target_node"):
                attrs = self.fields[field_name].widget.attrs
                attrs["data-dependency"] = "flow"
                attrs["data-dependency-model"] = "whatsapp.WhatsAppBotRule"
                attrs["data-dependency-field"] = "flow"
            self.fields["flow_dependency_value"] = forms.CharField(
                required=False,
                initial=flow.pk,
                widget=forms.HiddenInput(attrs={"id": "id_flow"}),
            )

        # The source node is known up front on both create (via the node
        # card's "+ Connect" link, which passes ?source_node=) and update
        # (the edge already has one). When it is, and that node type has a
        # fixed set of valid handles (condition branches, search_record's
        # found/not_found, buttons/list option ids), swap the free-text
        # source_handle field for a dropdown of exactly those - so the admin
        # picks the handle instead of retyping a string that has to match
        # what they already typed into the node's own config verbatim.
        source_node = source_node or getattr(self.instance, "source_node", None)
        if source_node is None and request:
            source_node = (
                flow.nodes.filter(
                    pk=request.GET.get("source_node") or request.POST.get("source_node")
                ).first()
                if flow
                else None
            )
        if source_node:
            handles = source_node.get_available_handles()
            if handles:
                current = self.instance.source_handle if self.instance.pk else None
                choices = list(handles)
                if current and current not in [value for value, _label in choices]:
                    choices.insert(0, (current, current))
                self.fields["source_handle"] = forms.ChoiceField(
                    choices=choices,
                    required=True,
                    label=_("Source Handle"),
                    help_text=_(
                        "Which branch/option of the source node this edge fires for."
                    ),
                    widget=forms.Select(
                        attrs={"class": "js-example-basic-single headselect"}
                    ),
                )

    def clean(self):
        cleaned_data = super().clean()
        source_node = cleaned_data.get("source_node")
        target_node = cleaned_data.get("target_node")
        if source_node and target_node and source_node.flow_id != target_node.flow_id:
            raise forms.ValidationError(
                _("Source and target nodes must belong to the same flow.")
            )
        return cleaned_data
