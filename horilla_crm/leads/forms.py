"""Forms for Lead model and Lead conversion process."""

# Standard library imports
import json
import logging

# Third-party imports (Django)
from django import forms
from django.utils.safestring import mark_safe

# First party imports (Horilla)
from horilla.auth.models import User
from horilla.contrib.core.mixins import OwnerQuerysetMixin
from horilla.contrib.core.utils import get_allowed_user_ids
from horilla.contrib.generics.forms import HorillaModelForm, HorillaMultiStepForm
from horilla.contrib.mail.models import (
    HorillaMailConfiguration,
    HorillaMailTemplate,
    IncomingMail,
)
from horilla.contrib.notifications.models import NotificationTemplate
from horilla.core.exceptions import ValidationError
from horilla.db.models import Q
from horilla.urls import reverse, reverse_lazy
from horilla.utils.choices import get_subdivision_choices, resolve_subdivision_choice
from horilla.utils.html import format_html
from horilla.utils.translation import gettext_lazy as _

# Local imports
from horilla_crm.accounts.models import Account
from horilla_crm.contacts.models import Contact
from horilla_crm.leads.form_mixins import (
    APPLY_FIELD,
    LeadAssignmentRuleFormMixin,
    _ApplyCheckboxReader,
)
from horilla_crm.opportunities.models import Opportunity

from .models import (
    EmailToLeadConfig,
    Lead,
    LeadAssignmentCondition,
    LeadAssignmentMatchCriteria,
    LeadStatus,
)
from .utils import build_lead_from_email

logger = logging.getLogger(__name__)

# Shows the Email to Lead "Assign using rules" box only while Create As is Lead
# and keeps its note in step with the checkbox.
ASSIGNMENT_BOX_SCRIPT = (
    "(function(){"
    "var box=document.getElementById('apply_assignment_rule_box');"
    "var sel=document.getElementById('id_create_as');"
    "if(!box||!sel)return;"
    "var cb=document.getElementById('id_apply_assignment_rule');"
    "var note=document.getElementById('apply_assignment_rule_note');"
    "function sync(){box.style.display=sel.value==='lead'?'':'none';"
    "note.textContent=cb.checked?note.dataset.on:note.dataset.off;}"
    "cb.addEventListener('change',sync);"
    "sel.addEventListener('change',sync);"
    "if(window.jQuery)window.jQuery(sel).on('change',sync);"
    "sync();})();"
)


class LeadFormClass(
    LeadAssignmentRuleFormMixin, OwnerQuerysetMixin, HorillaMultiStepForm
):
    """Form class for Lead model"""

    class Meta:
        """Meta class for LeadFormClass"""

        model = Lead
        fields = "__all__"
        exclude = ["lead_score"]

    step_fields = {
        1: [
            "lead_owner",
            "title",
            "first_name",
            "last_name",
            "email",
            "contact_number",
            "fax",
            "lead_source",
            "lead_status",
        ],
        2: ["lead_company", "no_of_employees", "industry", "annual_revenue"],
        3: ["country", "state", "city", "zip_code"],
        4: ["requirements"],
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["lead_status"].queryset = LeadStatus.objects.filter(is_final=False)
        self.fields["country"].widget.attrs.update(
            {
                "hx-get": reverse_lazy("core:get_country_subdivisions"),
                "hx-target": "#id_state",
                "hx-trigger": "change",
                "hx-swap": "innerHTML",
            }
        )
        self.fields["state"] = forms.ChoiceField(
            choices=[],
            label=self._meta.model._meta.get_field("state").verbose_name,
            required=False,
            widget=forms.Select(
                attrs={"id": "id_state", "class": "js-example-basic-single headselect"}
            ),
        )

        if "country" in self.data:
            country_code = self.data.get("country")
            self.fields["state"].choices = get_subdivision_choices(country_code)
        elif self.instance.pk and self.instance.country:
            self.fields["state"].choices = get_subdivision_choices(
                self.instance.country.code
            )
            self.fields["state"].initial = resolve_subdivision_choice(
                self.fields["state"].choices, self.instance.state
            )


class LeadSingleForm(LeadAssignmentRuleFormMixin, OwnerQuerysetMixin, HorillaModelForm):
    """
    Custom form for Lead to add HTMX attributes
    Inherits from HorillaModelForm to preserve all existing behavior.
    """

    field_order = [
        "lead_owner",
        "title",
        "first_name",
        "last_name",
        "email",
        "contact_number",
        "lead_source",
        "lead_status",
        "lead_company",
        "no_of_employees",
        "industry",
        "annual_revenue",
        "country",
        "state",
        "city",
        "zip_code",
        "fax",
        "requirements",
    ]

    class Meta:
        """Meta class for LeadStatusForm"""

        model = Lead
        fields = "__all__"
        exclude = ["lead_score"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["lead_status"].queryset = LeadStatus.objects.filter(is_final=False)
        self.fields["country"].widget.attrs.update(
            {
                "hx-get": reverse_lazy("core:get_country_subdivisions"),
                "hx-target": "#id_state",
                "hx-trigger": "change",
                "hx-swap": "innerHTML",
            }
        )
        self.fields["state"] = forms.ChoiceField(
            choices=[],
            label=self._meta.model._meta.get_field("state").verbose_name,
            required=False,
            widget=forms.Select(
                attrs={"id": "id_state", "class": "js-example-basic-single headselect"}
            ),
        )

        if "country" in self.data:
            country_code = self.data.get("country")
            self.fields["state"].choices = get_subdivision_choices(country_code)
        elif self.instance.pk and self.instance.country:
            self.fields["state"].choices = get_subdivision_choices(
                self.instance.country.code
            )
            self.fields["state"].initial = resolve_subdivision_choice(
                self.fields["state"].choices, self.instance.state
            )


class LeadConversionForm(forms.Form):
    """Form for converting a Lead into Account, Contact, and Opportunity"""

    # Account fields
    account_action = forms.ChoiceField(
        choices=[("create_new", "Create New"), ("select_existing", "Select Existing")],
        widget=forms.RadioSelect(
            attrs={
                "class": "border border-[#cbcbcb] w-3 h-3 text-[#e54f38] bg-white focus:ring-[#e54f38] cursor-pointer"
            }
        ),
        initial="create_new",
    )
    account_name = forms.CharField(
        max_length=255,
        required=False,
        widget=forms.TextInput(
            attrs={
                "class": "text-color-600 p-2 placeholder:text-xs  w-full border border-dark-50 rounded-md mt-1 focus-visible:outline-0 placeholder:text-dark-100 text-sm [transition:.3s] focus:border-primary-600",
                "placeholder": _("Enter Account Name"),
            }
        ),
    )
    existing_account = forms.ModelChoiceField(
        queryset=Account.objects.all(),
        required=False,
        empty_label=_("Select Account"),
        widget=forms.Select(
            attrs={
                "class": "select2-pagination w-full text-sm",
                "hx-get": "",  # Will be set dynamically
                "hx-target": "#opportunity-field",
                "hx-swap": "innerHTML",
                "hx-trigger": "change",
            }
        ),
    )

    # Contact fields
    contact_action = forms.ChoiceField(
        choices=[("create_new", "Create New"), ("select_existing", "Select Existing")],
        widget=forms.RadioSelect(
            attrs={
                "class": "border border-[#cbcbcb] w-3 h-3 text-[#e54f38] bg-white focus:ring-[#e54f38] cursor-pointer"
            }
        ),
        initial="create_new",
    )
    first_name = forms.CharField(
        max_length=100,
        required=False,
        widget=forms.TextInput(
            attrs={
                "class": "text-color-600 p-2 placeholder:text-xs pr-[40px] w-full border border-dark-50 rounded-md mt-1 focus-visible:outline-0 placeholder:text-dark-100 text-sm [transition:.3s] focus:border-primary-600",
                "placeholder": _("Enter First Name"),
            }
        ),
    )
    last_name = forms.CharField(
        max_length=100,
        required=False,
        widget=forms.TextInput(
            attrs={
                "class": "text-color-600 p-2 placeholder:text-xs pr-[40px] w-full border border-dark-50 rounded-md mt-1 focus-visible:outline-0 placeholder:text-dark-100 text-sm [transition:.3s] focus:border-primary-600",
                "placeholder": _("Enter Last Name"),
            }
        ),
    )
    existing_contact = forms.ModelChoiceField(
        queryset=Contact.objects.all(),
        required=False,
        empty_label=_("Select Contact"),
        widget=forms.Select(attrs={"class": "normal-seclect"}),
    )

    # Opportunity fields
    opportunity_action = forms.ChoiceField(
        choices=[("create_new", "Create New"), ("select_existing", "Select Existing")],
        widget=forms.RadioSelect(
            attrs={
                "class": "border border-[#cbcbcb] w-3 h-3 text-[#e54f38] bg-white focus:ring-[#e54f38] cursor-pointer"
            }
        ),
        initial="create_new",
    )
    opportunity_name = forms.CharField(
        max_length=255,
        required=False,
        widget=forms.TextInput(
            attrs={
                "class": "text-color-600 p-2 placeholder:text-xs pr-[40px] w-full border border-dark-50 rounded-md mt-1 focus-visible:outline-0 placeholder:text-dark-100 text-sm [transition:.3s] focus:border-primary-600",
                "placeholder": _("Enter Opportunity Name"),
            }
        ),
    )
    existing_opportunity = forms.ModelChoiceField(
        queryset=Opportunity.objects.none(),  # Start with empty queryset
        required=False,
        empty_label=_("Select Opportunity"),
        widget=forms.Select(attrs={"class": "normal-seclect"}),
    )

    # Owner field
    owner = forms.ModelChoiceField(
        queryset=User.objects.all(),
        required=True,
        empty_label=_("Select Owner"),
        widget=forms.Select(
            attrs={
                "class": "text-color-600 p-2 placeholder:text-xs pr-[40px] w-full border border-dark-50 rounded-md mt-1 focus-visible:outline-0 placeholder:text-dark-100 text-sm [transition:.3s] focus:border-primary-600"
            }
        ),
    )

    def __init__(self, *args, **kwargs):
        self.lead = kwargs.pop("lead", None)
        self.selected_account = kwargs.pop("selected_account", None)
        request = kwargs.pop("request", None)
        self.user = kwargs.pop("user", None) or getattr(request, "user", None)
        super().__init__(*args, **kwargs)

        if self.lead:
            # Pre-populate fields with lead data
            self.fields["account_name"].initial = self.lead.lead_company
            self.fields["first_name"].initial = self.lead.first_name
            self.fields["last_name"].initial = self.lead.last_name
            self.fields["opportunity_name"].initial = (
                f"{self.lead.lead_company} - Opportunity"
            )
            self.fields["owner"].initial = self.lead.lead_owner

            # Set HTMX URL for account selection
            self.fields["existing_account"].widget.attrs["hx-get"] = reverse(
                "leads:convert_lead", kwargs={"pk": self.lead.pk}
            )

        # Filter opportunities based on selected account
        if self.selected_account:
            self.fields["existing_opportunity"].queryset = Opportunity.objects.filter(
                account=self.selected_account
            )
        else:
            self.fields["existing_opportunity"].queryset = Opportunity.objects.none()

        if self.user is not None:
            for field in ("existing_account", "existing_contact"):
                model = self.fields[field].queryset.model
                self.fields[field].queryset = self.scope_queryset(
                    self.user, model, self.fields[field].queryset
                )
            self.fields["existing_opportunity"].queryset = self.scope_queryset(
                self.user,
                Opportunity,
                self.fields["existing_opportunity"].queryset,
            )
            self.fields["owner"].queryset = self.owner_queryset(self.user)

    # (model, full change permission, owner field) for "Select Existing"
    EXISTING_SCOPES = {
        Account: ("accounts.change_account", "account_owner"),
        Contact: ("contacts.change_contact", "contact_owner"),
        Opportunity: ("opportunities.change_opportunity", "owner"),
    }

    @classmethod
    def scope_queryset(cls, user, model, queryset):
        """
        Limit "Select Existing" records to what the user may link: everything
        with the full change permission, otherwise only records owned by the
        user or their subordinates.
        """
        perm, owner_field = cls.EXISTING_SCOPES[model]
        if user.has_perm(perm):
            return queryset
        return queryset.filter(**{f"{owner_field}__in": get_allowed_user_ids(user)})

    @staticmethod
    def owner_queryset(user):
        """
        Owners the user may assign: anyone with the full add permission on
        Account, Contact and Opportunity, otherwise the user and subordinates.
        """
        full_perms = (
            "accounts.add_account",
            "contacts.add_contact",
            "opportunities.add_opportunity",
        )
        users = User.objects.filter(is_active=True)
        if all(user.has_perm(perm) for perm in full_perms):
            return users
        return users.filter(pk__in=get_allowed_user_ids(user))

    @classmethod
    def get_select2_queryset(cls, request, model, field_name):
        """Scope the Select2 search results behind the conversion form fields."""
        user = request.user
        if model is User and field_name == "owner":
            return cls.owner_queryset(user)
        if model in cls.EXISTING_SCOPES:
            return cls.scope_queryset(user, model, model.objects.all())
        return None

    def clean(self):
        """Validate account, contact, and opportunity selections for conversion."""
        cleaned_data = super().clean()

        # Validate account
        account_action = cleaned_data.get("account_action")
        if account_action == "create_new":
            if not cleaned_data.get("account_name"):
                self.add_error(
                    "account_name",
                    _("Account name is required when creating new account."),
                )
        elif account_action == "select_existing":
            if not cleaned_data.get("existing_account"):
                self.add_error(
                    "existing_account", _("Please select an existing account.")
                )

        # Validate contact
        contact_action = cleaned_data.get("contact_action")
        if contact_action == "create_new":
            if not cleaned_data.get("first_name"):
                self.add_error(
                    "first_name", _("First name is required when creating new contact.")
                )
            if not cleaned_data.get("last_name"):
                self.add_error(
                    "last_name", _("Last name is required when creating new contact.")
                )
        elif contact_action == "select_existing":
            if not cleaned_data.get("existing_contact"):
                self.add_error(
                    "existing_contact", _("Please select an existing contact.")
                )

        # Validate opportunity
        opportunity_action = cleaned_data.get("opportunity_action")
        if opportunity_action == "create_new":
            if not cleaned_data.get("opportunity_name"):
                self.add_error(
                    "opportunity_name",
                    _("Opportunity name is required when creating new opportunity."),
                )
        elif opportunity_action == "select_existing":
            if not cleaned_data.get("existing_opportunity"):
                self.add_error(
                    "existing_opportunity", _("Please select an existing opportunity.")
                )

        return cleaned_data


class LeadStatusForm(HorillaModelForm):
    """
    Custom form for LeadStatus to add HTMX attributes to is_final field.
    Inherits from HorillaModelForm to preserve all existing behavior.
    """

    field_order = ["name", "probability", "order", "is_final"]

    class Meta:
        """Meta class for LeadStatusForm"""

        model = LeadStatus
        fields = "__all__"
        exclude = ["color"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Add HTMX attributes to is_final field to toggle order field visibility
        if "is_final" in self.fields:
            self.fields["is_final"].widget.attrs.update(
                {
                    "hx-post": reverse_lazy("leads:toggle_order_field"),
                    "hx-target": "#order_container",
                    "hx-swap": "outerHTML",
                    "hx-trigger": "change",
                }
            )
        if "order" in self.fields:
            # The order field is hidden client-side when "is_final" is checked,
            # so it may be submitted blank. LeadStatus.save() auto-assigns the
            # next available order when left unset.
            self.fields["order"].required = False


class EmailToLeadForm(HorillaModelForm):
    """
    Inherits from HorillaModelForm to preserve all existing behavior.
    """

    field_order = [
        "mail",
        "create_as",
        "owner",
        "apply_assignment_rule",
        "accept_emails_from",
        "keywords",
    ]

    class Meta:
        """Meta class for LeadStatusForm"""

        model = EmailToLeadConfig
        fields = "__all__"
        exclude = ["last_fetched"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["mail"].queryset = HorillaMailConfiguration.objects.filter(
            mail_channel="incoming", is_active=True
        )
        self._draw_assignment_checkbox_with_owner()

    def _draw_assignment_checkbox_with_owner(self):
        """
        Make the Owner widget draw the "Assign using rules" checkbox right
        below the owner field, so it follows the owner in Form Layout.
        """
        owner = self.fields.get("owner")
        if owner is None or "apply_assignment_rule" not in self.fields:
            return
        self.fields["apply_assignment_rule"].widget = _ApplyCheckboxReader()

        widget = owner.widget
        original_render = widget.render

        def render(name, value, attrs=None, renderer=None):
            field_html = original_render(name, value, attrs, renderer)
            return format_html("{}{}", field_html, self._checkbox_html())

        widget.render = render

    def _checkbox_html(self):
        """The checkbox, a note on what it does, and the script that shows
        both only while "Create As" is Lead."""
        if self.is_bound:
            checked = forms.CheckboxInput().value_from_datadict(
                self.data, self.files, self.add_prefix(APPLY_FIELD)
            )
        else:
            checked = self.initial.get(APPLY_FIELD, True)
        box = forms.CheckboxInput(
            attrs={
                "id": f"id_{APPLY_FIELD}",
                "class": "shrink-0 bg-[#E9EDF7] rounded-sm accent-primary-600",
                "style": "width: 14px; height: 14px",
            }
        ).render(self.add_prefix(APPLY_FIELD), checked)
        return format_html(
            '<div id="apply_assignment_rule_box">'
            '<p id="apply_assignment_rule_note" class="text-xs mt-1 text-gray-500" '
            'data-on="{}" data-off="{}"></p>'
            '<label for="id_apply_assignment_rule" class="mt-2 w-fit flex '
            'items-center gap-2 text-color-600 cursor-pointer" '
            'style="font-size: 12px">{}<span class="select-none">{}</span>'
            "</label></div><script>{}</script>",
            _(
                "The matching rule assigns the lead to one of its people by its "
                "assignment method (least lead count or round robin); the "
                "selected Owner is used when no rule matches."
            ),
            _("The selected Owner is always used."),
            box,
            _("Assign using rules"),
            mark_safe(ASSIGNMENT_BOX_SCRIPT),
        )


class InboxAddAsLeadForm(
    LeadAssignmentRuleFormMixin, OwnerQuerysetMixin, forms.ModelForm
):
    """
    Owner picker shown when an inbox email is added as a Lead.

    Works like the lead create form: the "Assign using rules" checkbox sits
    under Owner and, when ticked, limits the owner list to the people of the
    rule the email's lead matches. The rules are checked against the lead the
    email would create.
    """

    class Meta:
        """Meta class for InboxAddAsLeadForm"""

        model = Lead
        fields = ["lead_owner"]

    def __init__(self, data=None, *args, request=None, incoming_mail=None, **kwargs):
        self.request = request
        if incoming_mail is None and data:
            # The owner preview sends the mail id along with the form values.
            incoming_mail = IncomingMail.objects.filter(
                pk=data.get("mail") if str(data.get("mail", "")).isdigit() else None
            ).first()
        self.incoming_mail = incoming_mail
        if incoming_mail is not None:
            kwargs.setdefault(
                "instance",
                build_lead_from_email(
                    incoming_mail,
                    company=getattr(request, "active_company", None),
                ),
            )
        super().__init__(data, *args, **kwargs)
        owner = self.fields["lead_owner"]
        owner.required = True
        owner.widget.attrs.update(
            {"class": "js-example-basic-single headselect", "id": "id_lead_owner"}
        )
        if request is not None and not self.is_bound:
            self.initial.setdefault("lead_owner", request.user.pk)

    def _assignment_is_final(self):
        """The email already holds every value a rule looks at, even in the preview."""
        return True

    def _htmx_attrs(self):
        """Point the owner preview at this form and the email it is for."""
        attrs = super()._htmx_attrs()
        attrs["hx-vals"] = json.dumps(
            {"mode": "inbox", "mail": getattr(self.incoming_mail, "pk", "")}
        )
        return attrs


class AssignmentRuleConditionForm(OwnerQuerysetMixin, HorillaModelForm):
    """Form for creating and editing lead assignment rule conditions."""

    field_order = [
        "rule",
        "assign_to_type",
        "assign_to_users",
        "assign_to_roles",
        "assignment_method",
        "notify_method",
        "mail_template",
        "notification_template",
    ]

    def __init__(self, *args, **kwargs):
        kwargs["condition_model"] = LeadAssignmentMatchCriteria
        super().__init__(*args, **kwargs)

        current_type = "user"
        if self.instance and self.instance.pk:
            current_type = self.instance.assign_to_type or "user"
        elif self.data.get("assign_to_type"):
            current_type = self.data["assign_to_type"]

        self.fields["assign_to_type"].widget.attrs.update(
            {
                "hx-post": reverse_lazy("leads:toggle_assign_to_field"),
                "hx-target": "#assign_to_users_container",
                "hx-swap": "outerHTML",
                "hx-trigger": "change",
            }
        )
        self.fields["assign_to_users"].widget.attrs["container_style"] = (
            "" if current_type == "user" else "display:none"
        )
        self.fields["assign_to_roles"].widget.attrs["container_style"] = (
            "" if current_type == "role" else "display:none"
        )

        # --- notify_method conditional fields ---
        current_notify = ""
        if self.instance and self.instance.pk:
            current_notify = self.instance.notify_method or ""
        elif self.data.get("notify_method"):
            current_notify = self.data["notify_method"]

        lead_template_qs = Q(content_type__isnull=True) | Q(
            content_type__app_label="leads", content_type__model="lead"
        )
        self.fields["mail_template"].queryset = HorillaMailTemplate.objects.filter(
            lead_template_qs
        )
        self.fields["notification_template"].queryset = (
            NotificationTemplate.objects.filter(lead_template_qs)
        )

        self.fields["notify_method"].widget.attrs.update(
            {
                "hx-post": reverse_lazy("leads:toggle_notify_method_field"),
                "hx-target": "#mail_template_container",
                "hx-swap": "outerHTML",
                "hx-trigger": "change",
                "hx-include": "[name='mail_template'],[name='notification_template']",
            }
        )
        show_mail = current_notify in ("email", "both")
        show_notification = current_notify in ("notification", "both")
        self.fields["mail_template"].widget.attrs["container_style"] = (
            "" if show_mail else "display:none"
        )
        self.fields["notification_template"].widget.attrs["container_style"] = (
            "" if show_notification else "display:none"
        )

    def clean(self):
        cleaned_data = super().clean()
        condition_rows = self._extract_condition_rows()
        if not condition_rows:
            raise ValidationError("At least one matching criterion must be provided.")
        cleaned_data["condition_rows"] = condition_rows
        return cleaned_data

    class Meta:
        """
        Meta options for AssignmentRuleConditionForm. Specifies the model and fields to include in the form.
        """

        model = LeadAssignmentCondition
        fields = "__all__"


class WebToLeadForm(HorillaModelForm):
    """Base of the public web-to-lead form; the view keeps only the selected fields.

    A ``HorillaModelForm`` so extension fields (e.g. custom fields) are added
    and saved like on every other Lead form.
    """

    class Meta:
        """Meta class for WebToLeadForm"""

        model = Lead
        fields = "__all__"
